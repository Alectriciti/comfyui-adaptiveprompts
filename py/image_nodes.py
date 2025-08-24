import os
import re
import hashlib
import numpy as np
import torch

import folder_paths
import node_helpers
import json

from PIL import Image, ImageOps, ImageSequence
from PIL.PngImagePlugin import PngInfo

from comfy.cli_args import args


class SaveImageAndText:
    def __init__(self):
        self.output_dir = folder_paths.get_output_directory()
        self.type = "output"
        self.prefix_append = ""
        self.compress_level = 4

    @classmethod
    def INPUT_TYPES(s):
        return {
            "required": {
                "images": ("IMAGE", {"tooltip": "The images to save."}),
                "filename_prefix": ("STRING", {
                    "default": "ComfyUI",
                    "tooltip": "The prefix for the files to save. This may include formatting info such as %date:yyyy-MM-dd%.\nThe .txt file will be saved with the same name."
                }),
                "prompt_data": ("STRING", {
                    "multiline": False,
                    "default": "",
                    "tooltip": "Text data to save alongside the image, written into a .txt file."
                })
            },
            "hidden": {
                "prompt": "PROMPT",
                "extra_pnginfo": "EXTRA_PNGINFO"
            },
        }

    RETURN_TYPES = ()
    FUNCTION = "save_images_and_text"

    OUTPUT_NODE = True
    CATEGORY = "image"
    DESCRIPTION = "Saves input images and also writes a .txt file with user-specified content."

    def save_images_and_text(self, images, filename_prefix="ComfyUI", prompt_data="", prompt=None, extra_pnginfo=None):
        filename_prefix += self.prefix_append
        full_output_folder, filename, counter, subfolder, filename_prefix = folder_paths.get_save_image_path(
            filename_prefix, self.output_dir, images[0].shape[1], images[0].shape[0]
        )

        results = list()
        for (batch_number, image) in enumerate(images):
            # Convert tensor to image
            i = 255. * image.cpu().numpy()
            img = Image.fromarray(np.clip(i, 0, 255).astype(np.uint8))

            # Metadata for PNG
            metadata = None
            if not args.disable_metadata:
                metadata = PngInfo()
                if prompt is not None:
                    metadata.add_text("prompt", json.dumps(prompt))
                if extra_pnginfo is not None:
                    for x in extra_pnginfo:
                        metadata.add_text(x, json.dumps(extra_pnginfo[x]))

            # Build deterministic filename
            filename_with_batch_num = filename.replace("%batch_num%", str(batch_number))
            file_base = f"{filename_with_batch_num}_{counter:05}_"
            img_file = f"{file_base}.png"
            txt_file = f"{file_base}.txt"

            # Save image
            img.save(os.path.join(full_output_folder, img_file), pnginfo=metadata, compress_level=self.compress_level)

            # Save text file (only if something provided)
            if prompt_data is not None and prompt_data.strip() != "":
                with open(os.path.join(full_output_folder, txt_file), "w", encoding="utf-8") as f:
                    f.write(prompt_data)

            results.append({
                "filename": img_file,
                "subfolder": subfolder,
                "type": self.type
            })
            counter += 1

        return {"ui": {"images": results}}




class LoadImageAndMeta:
    """
    Extended LoadImage for ComfyUI that also returns:
      - Width (INT)
      - Height (INT)
      - Text Data (STRING) from a sidecar .txt (same basename)
    This version is resilient: if basename+'.txt' isn't found it searches the image folder
    with several heuristics (trim trailing digits/underscores, underscores<->spaces, etc.)
    """

    @classmethod
    def INPUT_TYPES(cls):
        input_dir = folder_paths.get_input_directory()
        files = [f for f in os.listdir(input_dir) if os.path.isfile(os.path.join(input_dir, f))]
        files = folder_paths.filter_files_content_types(files, ["image"])
        return {
            "required": {
                "image": (sorted(files), {"image_upload": True}),
            }
        }

    CATEGORY = "image"

    # IMAGE, MASK, WIDTH, HEIGHT, TEXT
    RETURN_TYPES = ("IMAGE", "MASK", "INT", "INT", "STRING")
    RETURN_NAMES = ("image", "mask", "width", "height", "text")

    FUNCTION = "load_image"

    # --- helper: try many heuristics to find a matching .txt for an image file ---
    def _find_matching_txt(self, image_path: str) -> str | None:
        """
        Return the path to a matching .txt file, or None.
        Heuristics (in priority order):
          1) exact basename + ".txt" (case-sensitive)
          2) exact basename + ".txt" (case-insensitive)
          3) basename trimmed of trailing underscores/digits + ".txt"
          4) underscore/space normalized matches
          5) substring contains matches (last resort)
        """
        directory = os.path.dirname(image_path)
        base = os.path.splitext(os.path.basename(image_path))[0]  # e.g. "coolimage5000_00001_"
        txt_exact = os.path.join(directory, base + ".txt")
        if os.path.exists(txt_exact):
            return txt_exact

        # gather all .txt files in that directory
        try:
            candidates = [f for f in os.listdir(directory) if f.lower().endswith(".txt")]
        except OSError:
            return None

        if not candidates:
            return None

        base_lower = base.lower()

        # 2) case-insensitive exact
        for f in candidates:
            name = os.path.splitext(f)[0]
            if name.lower() == base_lower:
                return os.path.join(directory, f)

        # 3) trim trailing underscores/digits from base and compare
        trimmed = re.sub(r'[_\-\s]*\d+$', '', base_lower)
        if trimmed != base_lower:
            for f in candidates:
                name = os.path.splitext(f)[0].lower()
                if name == trimmed:
                    return os.path.join(directory, f)

        # 4) underscore/space normalization: compare both directions
        def normalize_us_space(s: str):
            return re.sub(r'\s+', ' ', s.replace('_', ' ')).strip()

        norm_base = normalize_us_space(base_lower)
        for f in candidates:
            name = os.path.splitext(f)[0].lower()
            if normalize_us_space(name) == norm_base:
                return os.path.join(directory, f)

        # 5) try "contains" matches (name contains base or base contains name)
        # prefer longer matches (more specific)
        cand_pairs = []
        for f in candidates:
            name = os.path.splitext(f)[0].lower()
            if base_lower in name or name in base_lower:
                cand_pairs.append((len(name), f))
        if cand_pairs:
            cand_pairs.sort(reverse=True)  # prefer longer match first
            return os.path.join(directory, cand_pairs[0][1])

        return None

    def load_image(self, image):
        image_path = folder_paths.get_annotated_filepath(image)

        # Load image using node_helpers (same as Comfy's LoadImage)
        img = node_helpers.pillow(Image.open, image_path)

        output_images = []
        output_masks = []
        w, h = None, None

        excluded_formats = ['MPO']

        for i in ImageSequence.Iterator(img):
            i = node_helpers.pillow(ImageOps.exif_transpose, i)

            if i.mode == 'I':
                i = i.point(lambda i: i * (1 / 255))
            image_rgb = i.convert("RGB")

            if len(output_images) == 0:
                w = image_rgb.size[0]
                h = image_rgb.size[1]

            # skip frames that don't match first frame size
            if image_rgb.size[0] != w or image_rgb.size[1] != h:
                continue

            arr = np.array(image_rgb).astype(np.float32) / 255.0
            tensor_img = torch.from_numpy(arr)[None,]

            if 'A' in i.getbands():
                mask = np.array(i.getchannel('A')).astype(np.float32) / 255.0
                mask = 1. - torch.from_numpy(mask)
            elif i.mode == 'P' and 'transparency' in i.info:
                mask = np.array(i.convert('RGBA').getchannel('A')).astype(np.float32) / 255.0
                mask = 1. - torch.from_numpy(mask)
            else:
                mask = torch.zeros((64,64), dtype=torch.float32, device="cpu")

            output_images.append(tensor_img)
            output_masks.append(mask.unsqueeze(0))

        if len(output_images) > 1 and img.format not in excluded_formats:
            output_image = torch.cat(output_images, dim=0)
            output_mask = torch.cat(output_masks, dim=0)
        else:
            output_image = output_images[0]
            output_mask = output_masks[0]

        # --- find and load matching .txt (robust) ---
        text_data = ""
        txt_path = self._find_matching_txt(image_path)
        if txt_path:
            try:
                with open(txt_path, "r", encoding="utf-8") as f:
                    text_data = f.read()
            except Exception as e:
                # return a short error marker so user can see there's an issue reading it
                text_data = f"[Error reading {os.path.basename(txt_path)}: {e}]"

        return (output_image, output_mask, w, h, text_data)

    @classmethod
    def IS_CHANGED(cls, image):
        image_path = folder_paths.get_annotated_filepath(image)
        m = hashlib.sha256()
        with open(image_path, 'rb') as f:
            m.update(f.read())
        return m.digest().hex()

    @classmethod
    def VALIDATE_INPUTS(cls, image):
        if not folder_paths.exists_annotated_filepath(image):
            return "Invalid image file: {}".format(image)
        return True