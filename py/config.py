import json
import os

CONFIG_PATH = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "config.json"))

DEFAULT_CONFIG = {
    "default_rng_mode": "Adaptive",
    "search_depth_limit": 80,
    "hide_comments": True,
    "resolution_strategy": "Scoped",  # "Scoped" or "Aggressive"
    "missing_wildcard_behavior": "Inject Warning"
}

class AdaptiveConfig:
    def __init__(self):
        self.config = DEFAULT_CONFIG.copy()
        self.load()

    def load(self):
        if os.path.exists(CONFIG_PATH):
            # Config Validation
            try:
                with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                    loaded = json.load(f)
                # Prune orphaned keys and load valid ones
                keys_to_remove = []
                for key, value in loaded.items():
                    if key in DEFAULT_CONFIG:
                        self.config[key] = value
                    else:
                        keys_to_remove.append(key)

                # Check if we need to add new default keys
                missing_keys = set(DEFAULT_CONFIG.keys()) - set(loaded.keys())
                
                # Save dynamically if the config was altered in any way
                if missing_keys or keys_to_remove:
                    self.save()
                    
            except Exception as e:
                print(f"[Adaptive Prompts] Failed to load config: {e}")
        else:
            self.save()

    def save(self):
        try:
            with open(CONFIG_PATH, "w", encoding="utf-8") as f:
                json.dump(self.config, f, indent=4)
        except Exception as e:
            print(f"[Adaptive Prompts] Failed to save config: {e}")

    def get(self, key):
        return self.config.get(key, DEFAULT_CONFIG.get(key))

    def set(self, key, value):
        self.config[key] = value
        self.save()

# Instantiate the singleton
config_instance = AdaptiveConfig()

def set_config(key, value):
    config_instance.config[key] = value
    config_instance.save()

def get_config(key):
    return config_instance.config.get(key, DEFAULT_CONFIG.get(key))

def get_all_config(): 
    return config_instance.config