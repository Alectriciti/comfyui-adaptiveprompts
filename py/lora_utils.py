import json
import re
import folder_paths
import random
from pathlib import Path
import numpy as np
import logging

# ComfyUI core imports
import comfy.sd
import comfy.utils

from .generator import evaluate_prompt_core, SeededRandom
from .misc_utils import *

DEBUG = False

# --- UTILITY CLASS ---

class LoraTagUtility:
    @staticmethod
    def _deep_search_tags(data, target_keys, tags_dict):
        """Recursively parses dictionaries, lists, and stringified JSON to find target keys."""
        if isinstance(data, dict):
            for k, v in data.items():
                if k in target_keys:
                    try:
                        resolved_val = json.loads(v) if isinstance(v, str) else v
                        if isinstance(resolved_val, dict):
                            for sub_key, sub_val in resolved_val.items():
                                if isinstance(sub_val, dict):
                                    for tag, count in sub_val.items():
                                        tags_dict[tag] = tags_dict.get(tag, 0) + int(count)
                                else:
                                    tags_dict[sub_key] = tags_dict.get(sub_key, 0) + int(sub_val)
                    except Exception:
                        pass
                else:
                    if isinstance(v, (dict, list)):
                        LoraTagUtility._deep_search_tags(v, target_keys, tags_dict)
                    elif isinstance(v, str) and (v.startswith('{') or v.startswith('[')):
                        try:
                            parsed = json.loads(v)
                            LoraTagUtility._deep_search_tags(parsed, target_keys, tags_dict)
                        except Exception:
                            pass
        elif isinstance(data, list):
            for item in data:
                LoraTagUtility._deep_search_tags(item, target_keys, tags_dict)

    @staticmethod
    def get_lora_metadata(lora_path):
        """Reads the .safetensors header on the fly to extract tag metadata."""
        tags_dict = {}
        try:
            with open(lora_path, "rb") as f:
                # Read exactly 8 bytes for the little-endian header length descriptor
                header_size = int.from_bytes(f.read(8), "little")
                header = json.loads(f.read(header_size))
                metadata = header.get("__metadata__", {})
                
                possible_keys = ["ss_tag_frequency", "tag_frequency"]
                LoraTagUtility._deep_search_tags(metadata, possible_keys, tags_dict)
        except Exception as e:
            if DEBUG:
                print(f"[LoraTagUtility] Error parsing header for {lora_path}: {e}")

        return tags_dict

    @staticmethod
    def find_lora_file(target_name):
        lora_files = folder_paths.get_filename_list("loras")
        for lora_file in lora_files:
            if Path(lora_file).stem == target_name:
                return folder_paths.get_full_path("loras", lora_file)
        return None

# --- UNIFIED LOAD LORA TAGS NODE ---

class LoadLoraTags:
    def __init__(self):
        self.tag_pattern = re.compile(r"<lora:[^>]+>")
        self.loaded_lora = None

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "text": ("STRING", {
                    "multiline": True, 
                    "default": "",
                    "tooltip": "Input text. Supports <lora:name>, <lora:name:weight>, <lora:name:unet:clip>, or <lora:name:unet:clip:keyword>."
                }),
                "compression_threshold": ("FLOAT", {
                    "default": 1.0, "min": 0.1, "max": 10.0, "step": 0.1,
                    "tooltip": "The maximum combined weight allowed before compression kicks in. This only affects model and clip, not keywords"
                }),
                "compression_ratio": ("FLOAT", {
                    "default": 2.0, "min": 1.0, "max": 100.0, "step": 0.5,
                    "tooltip": "How aggressively to compress excess weight. 1.0 = Off. 2.0 = 2:1 reduction. 100.0 = Hard Limiter."
                }),
                "base_keywords": ("INT", {
                    "default": 5, "min": 0, "max": 100,
                    "tooltip": "The base number of keywords extracted when a LoRA's keyword weight is exactly 1.0."
                }),
                "sort_mode": (["Top Frequency", "Weighted Random", "Random"], {
                    "default": "Top Frequency",
                    "tooltip": "How to sort the combined final list of all extracted keywords."
                }),
                "keyword_extraction_randomness": ("FLOAT", {
                    "default": 0.125, "min": 0.0, "max": 1.0, "step": 0.01,
                    "tooltip": (
                        "Blend between Frequency and Randomness.\n"
                        "0.0: Pure Frequency (Always picks top tags).\n"
                        "1.0: Pure Randomness (Ignores frequency, fully shuffled).\n"
                        "Values in between blend the two, allowing occasional variety in tag selection."
                    )
                }),
                "apply_keywords_to_prompt": ("BOOLEAN", {
                    "default": True,
                    "tooltip": "If true, extracted keywords are mixed into the prompt. If false, lora tags are stripped and keywords are ignored, leaving only the prompt text."
                }),
                "seed": ("INT", {
                    "default": 0, "min": 0, "max": 0xffffffffffffffff,
                    "tooltip": "Locks the randomness for prompt evaluation and keyword selection."
                }),
            },
            "optional": {
                "model": ("MODEL",),
                "clip": ("CLIP",),
            }
        }

    RETURN_TYPES = ("MODEL", "CLIP", "STRING", "STRING", "STRING")
    RETURN_NAMES = ("model", "clip", "prompt", "keywords", "lora_names")
    FUNCTION = "process"
    CATEGORY = "loaders"

    def process(self, text, compression_threshold, compression_ratio, base_keywords, 
                sort_mode, keyword_extraction_randomness, apply_keywords_to_prompt, seed, model=None, clip=None):
        
        # 1. Adaptive Prompts Core Evaluation (Isolated pass)
        rng = SeededRandom(seed)
        evaluated_text = evaluate_prompt_core(
            prompt=text, 
            rng=rng, 
            wildcard_dir="", 
            resolved_vars={}, 
            hide_comments=True
        )

        random.seed(seed)
        safe_np_seed = seed % (2**32)
        np.random.seed(safe_np_seed)
        
        founds = self.tag_pattern.findall(evaluated_text)
        if not founds: 
            # Cleanup stray commas and return if no tags found
            clean_text = re.sub(r'(,\s*){2,}', ', ', evaluated_text)
            return (model, clip, clean_text, "", "")

        # 2. Parse Tags & Build Weight Profiles
        lora_entries = []
        for f in founds:
            parts = f[1:-1].split(":")
            if parts[0].lower() != "lora" or len(parts) < 2: 
                continue
            
            name = parts[1]
            u_weight, c_weight, k_weight = 1.0, 1.0, 1.0
            args = parts[2:]
            
            try:
                if len(args) == 1:
                    u_weight = c_weight = k_weight = float(args[0])
                elif len(args) == 2:
                    u_weight = float(args[0])
                    c_weight = float(args[1])
                    k_weight = u_weight
                elif len(args) >= 3:
                    u_weight = float(args[0])
                    c_weight = float(args[1])
                    k_weight = float(args[2])
            except ValueError:
                pass # Fallback to 1.0 defaults if parsing fails
                
            lora_entries.append({
                "match": f,
                "name": name,
                "u": u_weight,
                "c": c_weight,
                "k": k_weight
            })

        valid_lora_entries = []
        missing_loras = []
        loaded_summary = []

        for item in lora_entries:
            full_path = LoraTagUtility.find_lora_file(item["name"])
            if full_path:
                item["full_path"] = full_path # Cache the path so we don't look it up twice
                valid_lora_entries.append(item)
            else:
                missing_loras.append(item['name'])

        # 3. Apply Weight Compression Algorithm
        total_mag = sum(abs(item['u']) for item in valid_lora_entries)
        compression_factor = 1.0
        
        if total_mag > compression_threshold and compression_ratio > 1.0:
            excess = total_mag - compression_threshold
            compressed_excess = excess / compression_ratio
            new_total = compression_threshold + compressed_excess
            compression_factor = new_total / total_mag
            
            for item in valid_lora_entries:
                item['u'] *= compression_factor
                item['c'] *= compression_factor
                #item['k'] *= compression_factor # uncomment this line to include keywords in compression


        # 4. Model Loading & Keyword Resolution
        loaded_loras = set()
        model_lora = model
        clip_lora = clip
        
        all_selected_keywords = []
        resolved_names = []
        tag_replacements = {item["match"]: "" for item in lora_entries}

        for item in valid_lora_entries:
            full_path = item["full_path"]
            final_display_name = item["name"]

            # Log success
            log_entry = f"[{item['name']}:{item['u']:.3f}:{item['c']:.3f}:{item['k']:.3f}]"
            loaded_summary.append(log_entry)
            
            # --- Model Injection ---
            if (model_lora is not None or clip_lora is not None) and full_path not in loaded_loras:
                if abs(item['u']) > 0.001 or abs(item['c']) > 0.001:
                    lora = None
                    if self.loaded_lora is not None and self.loaded_lora[0] == full_path:
                        lora = self.loaded_lora[1]
                    else:
                        temp = self.loaded_lora
                        self.loaded_lora = None
                        del temp
                        
                    if lora is None:
                        lora = comfy.utils.load_torch_file(full_path, safe_load=True)
                        self.loaded_lora = (full_path, lora)

                    model_lora, clip_lora = comfy.sd.load_lora_for_models(
                        model_lora, clip_lora, lora, item['u'], item['c']
                    )
                    loaded_loras.add(full_path)

            # --- Sidecar Metadata ---
            metadata_path = Path(full_path).with_suffix('.metadata.json')
            if metadata_path.exists():
                try:
                    with open(metadata_path, 'r', encoding='utf-8') as m_file:
                        sidecar_data = json.load(m_file)
                        if sidecar_data.get("model_name"):
                            final_display_name = sidecar_data["model_name"]
                except Exception as e:
                    print(f"\033[31m[Adaptive Prompts] Error reading metadata for {item['name']}: {e}\033[0m")
            
            # --- Keyword Extraction ---
            if abs(item['k']) > 0.001:
                tags_dict = LoraTagUtility.get_lora_metadata(full_path)
                if tags_dict:
                    quota = max(1, round(base_keywords * abs(item['k'])))
                    items = list(tags_dict.items())
                    max_freq = max([v for _, v in items]) if items else 1
                    
                    scored_items = []
                    for tag, freq in items:
                        norm_freq = freq / max_freq
                        random_component = random.random()
                        score = ((1.0 - keyword_extraction_randomness) * norm_freq) + \
                                (keyword_extraction_randomness * random_component)
                        scored_items.append((tag, score))
                    
                    scored_items.sort(key=lambda x: x[1], reverse=True)
                    top_n_tuples = scored_items[:quota]

                    if sort_mode == "Top Frequency":
                        top_n_tuples.sort(key=lambda x: x[1], reverse=True)
                    elif sort_mode == "Weighted Random":
                        top_n_tuples.sort(key=lambda x: x[1] * random.uniform(0.1, 2.0), reverse=True)
                    elif sort_mode == "Random":
                        random.shuffle(top_n_tuples)

                    local_tags = [t[0] for t in top_n_tuples]
                    tag_replacements[item["match"]] = ", ".join(local_tags)
                    all_selected_keywords.extend(top_n_tuples)

            resolved_names.append(final_display_name)

        # Print logs to console
        if loaded_summary:
            logging.info(f"{ADAPTIVE_PROMPTS} Loras Loaded ({len(loaded_summary)}): {', '.join(loaded_summary)}")
        
        if missing_loras:
            logging.error(f"{ADAPTIVE_PROMPTS} Loras Not Found: {', '.join(missing_loras)}")

        # 5. Inject Keywords into Prompt
        final_prompt = evaluated_text
        for f in founds:
            replacement = tag_replacements.get(f, "")
            if apply_keywords_to_prompt:
                final_prompt = final_prompt.replace(f, replacement, 1)
            else:
                final_prompt = final_prompt.replace(f, "", 1)
            
        # Clean up commas
        #final_prompt = re.sub(r'(,\s*){2,}', ', ', final_prompt)
        #final_prompt = re.sub(r'^\s*,\s*', '', final_prompt)
        #final_prompt = re.sub(r',\s*$', '', final_prompt).strip()

        # 6. Global Keyword Sorting
        if sort_mode == "Top Frequency":
            all_selected_keywords.sort(key=lambda x: x[1], reverse=True)
        elif sort_mode == "Weighted Random":
            all_selected_keywords.sort(key=lambda x: x[1] * random.uniform(0.1, 2.0), reverse=True)
        elif sort_mode == "Random":
            random.shuffle(all_selected_keywords)
        
        final_global_tags = [t[0] for t in all_selected_keywords]

        return (model_lora, clip_lora, final_prompt, ", ".join(final_global_tags), "\n".join(resolved_names))


