import json
import os

CONFIG_PATH = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "config.json"))

DEFAULT_CONFIG = {
    "default_rng_mode": "Adaptive",
    "search_depth_limit": 80,
    "hide_comments": True
}

class AdaptiveConfig:
    def __init__(self):
        self.config = DEFAULT_CONFIG.copy()
        self.load()

    def load(self):
        if os.path.exists(CONFIG_PATH):
            try:
                with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                    loaded = json.load(f)
                
                # Check if there are new defaults that the user's config.json doesn't have
                missing_keys = set(DEFAULT_CONFIG.keys()) - set(loaded.keys())
                
                self.config.update(loaded)
                
                # Actively update the existing config file with the new default keys
                if missing_keys:
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

# In config.py

def set_config(key, value):
    # Update the in-memory dictionary first
    config_instance.config[key] = value
    # Then persist to disk
    config_instance.save()

def get_config(key):
    # This now pulls the fresh value from the in-memory dict
    return config_instance.config.get(key, DEFAULT_CONFIG.get(key))

def get_all_config(): 
    return config_instance.config