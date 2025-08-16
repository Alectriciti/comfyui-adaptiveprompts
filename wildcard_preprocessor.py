import os
import re

class WildcardPreprocessor:
    def __init__(self, wildcard_dir):
        self.wildcard_dir = wildcard_dir
        self.cache = {}  # Maps wildcard_name -> list of valid words

    def preprocess(self):
        """Load all wildcard files into memory, ignoring metadata and comments."""
        for filename in os.listdir(self.wildcard_dir):
            if not filename.endswith(".txt"):
                continue

            wildcard_name = os.path.splitext(filename)[0].lower()
            values = []

            filepath = os.path.join(self.wildcard_dir, filename)
            with open(filepath, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith("#") or line.startswith("!"):
                        continue

                    # Remove inline comments after unescaped #
                    line = re.split(r'(?<!\\)#', line)[0].strip()
                    if line:
                        values.append(line)

            self.cache[wildcard_name] = values

    def get_cache(self):
        return self.cache