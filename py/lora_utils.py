import json
import re
import folder_paths
import random
from pathlib import Path
import numpy as np

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

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "text": ("STRING", {
                    "multiline": True, 
                    "default": "",
                    "tooltip": "Input text containing <lora:name:weight> tags."
                }),
                "VALUE_MODE": (["total_keywords", "per_lora_scaled", "per_lora_exact"], {
                    "default": "per_lora_scaled",
                    "tooltip": "How VALUE is applied. 'total_keywords' splits VALUE proportionally among all LoRAs based on weight. 'per_lora_scaled' multiplies VALUE by the LoRA's weight. 'per_lora_exact' ignores weight and gives exactly VALUE tags to each."
                }),
                "VALUE": ("INT", {
                    "default": 5, "min": -1, "max": 100,
                    "tooltip": "The target number of keywords. Set to -1 to extract every available tag from the metadata."
                }),
                "TAG_SELECTION": (["tag_frequency", "random", "weighted_random"], {
                    "default": "tag_frequency",
                    "tooltip": "How to pick keywords from the LoRA's pool. 'tag_frequency' grabs the most highly trained words. 'random' picks blindly. 'weighted_random' favors frequent words but allows rare ones to slip in."
                }),
                "SORTING_MODE": (["tag_frequency", "random", "none", "weighted_random"], {
                    "default": "tag_frequency",
                    "tooltip": "How to order the final combined list of keywords. 'tag_frequency' puts the strongest words from all combined LoRAs at the front of the prompt."
                }),
                "seed": ("INT", {
                    "default": 0, "min": 0, "max": 0xffffffffffffffff,
                    "tooltip": "Locks the randomness for selection and sorting."
                }),
            }
        }

    RETURN_TYPES = ("STRING", "STRING")
    RETURN_NAMES = ("keywords", "lora_names")
    FUNCTION = "process"
    CATEGORY = "loaders"

    def process(self, text, VALUE_MODE, VALUE, TAG_SELECTION, SORTING_MODE, seed):
        random.seed(seed)
        
        founds = self.tag_pattern.findall(text)
        if not founds: 
            return ("", "")

        lora_data = []
        resolved_names = []
        total_weight = 0

        for f in founds:
            tag = f[1:-1].split(":")
            if tag[0].lower() != "lora" or len(tag) < 2: 
                continue
            
            tag_lora_name = tag[1]
            weight = float(tag[2]) if len(tag) > 2 else 1.0
            
            full_path = LoraTagUtility.find_lora_file(tag_lora_name)
            file_found = full_path is not None
            
            # --- Name Resolution ---
            final_display_name = tag_lora_name
            if file_found:
                # Check for sidecar .metadata.json
                metadata_path = Path(full_path).with_suffix('.metadata.json')
                if metadata_path.exists():
                    try:
                        with open(metadata_path, 'r', encoding='utf-8') as m_file:
                            sidecar_data = json.load(m_file)
                            if sidecar_data.get("model_name"):
                                final_display_name = sidecar_data["model_name"]
                    except Exception as e:
                        if DEBUG: print(f"Error reading sidecar metadata for {tag_lora_name}: {e}")
                
                # --- Keyword Resolution ---
                tags = LoraTagUtility.get_lora_metadata(full_path)
                if tags:
                    lora_data.append({"name": tag_lora_name, "weight": weight, "tags": tags})
                    total_weight += weight

            resolved_names.append(final_display_name)

        if not lora_data: 
            return ("", "\n".join(resolved_names))

        # --- Process Keywords ---
        results = []
        for item in lora_data:
            # 1. Determine Quota based on unified VALUE_MODE
            if VALUE == -1:
                quota = len(item["tags"])
            elif VALUE_MODE == "total_keywords":
                # Distribute the VALUE pool proportionally based on this LoRA's weight
                quota = max(1, round((item["weight"] / total_weight) * VALUE)) if total_weight > 0 else 1
            elif VALUE_MODE == "per_lora_exact":
                # Fixed amount regardless of weight
                quota = max(1, VALUE)
            else: # "per_lora_scaled"
                # Base VALUE multiplied by the LoRA's specific strength
                quota = max(1, round(VALUE * item["weight"]))

            # 2. Select Tags
            tags_items = list(item["tags"].items()) 
            
            if TAG_SELECTION == "tag_frequency":
                tags_items.sort(key=lambda x: x[1], reverse=True)
                selected = tags_items[:quota]
            elif TAG_SELECTION == "random":
                selected = random.sample(tags_items, min(quota, len(tags_items)))
            elif TAG_SELECTION == "weighted_random":
                tags, freqs = zip(*tags_items)
                total_f = sum(freqs)
                probs = [f / total_f for f in freqs]
                selected_indices = np.random.choice(len(tags), size=min(quota, len(tags)), p=probs, replace=False)
                selected = [tags_items[i] for i in selected_indices]
            else: 
                selected = tags_items[:quota]

            results.extend(selected)

        # 3. Sort Final Output
        if SORTING_MODE == "tag_frequency":
            results.sort(key=lambda x: x[1], reverse=True)
        elif SORTING_MODE == "random":
            random.shuffle(results)
        elif SORTING_MODE == "weighted_random":
            results.sort(key=lambda x: x[1] * random.uniform(0.1, 2.0), reverse=True)
        
        final_tags = [t[0] for t in results]
        
        return (", ".join(final_tags), "\n".join(resolved_names))


