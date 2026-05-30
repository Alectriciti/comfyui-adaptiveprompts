import { app } from "../../scripts/app.js";
import { api } from "../../scripts/api.js";

// 1. Constants (Your "public static final String" equivalents)
const ID_PREFIX = "AdaptivePrompts.";
const SETTING_DEPTH = ID_PREFIX + "search_depth_limit";
const SETTING_BFS = ID_PREFIX + "enable_bfs";
const SETTING_RNG = ID_PREFIX + "default_rng_mode";
const SETTING_COMMENTS = ID_PREFIX + "hide_comments";

// 2. The Python Synchronization Hook
async function syncToBackend(key, value) {
    try {
        await api.fetchApi("/adaptive_prompts/config", {
            method: "POST",
            body: JSON.stringify({ [key]: value })
        });
    } catch (e) {
        console.error("[Adaptive Prompts] Failed to sync config to Python backend:", e);
    }
}

// 3. Extension Registration
app.registerExtension({
    name: "AdaptivePrompts.Settings",

    // THE DECLARATIVE ARRAY: ComfyUI reads this instantly. No async waiting!
    settings: [
        {
            id: SETTING_RNG,
            name: "Default RNG Mode",
            type: "combo",
            options: ["Adaptive", "Legacy"],
            tooltip: "Adaptive: Identity-based RNG (rearrangeable prompts). Legacy: Sequential RNG (domino-effect).",
            defaultValue: "Adaptive",
            category: ["Adaptive Prompts", "Generation", "RNG Mode"],
            onChange: (value) => syncToBackend("default_rng_mode", value)
        },
        {
            id: SETTING_DEPTH,
            name: "Search Depth Limit",
            type: "slider",
            attrs: { min: 10, max: 200, step: 1 },
            defaultValue: 80,
            // Categories create nested folders in the Settings UI
            category: ["Adaptive Prompts", "Resolution", "Search Depth"],
            onChange: (value) => syncToBackend("search_depth_limit", value)
        },
        {
            id: SETTING_COMMENTS,
            name: "Hide Comments by Default",
            type: "boolean",
            defaultValue: true,
            category: ["Adaptive Prompts", "Formatting", "Comments"],
            onChange: (value) => syncToBackend("hide_comments", value)
        }
    ],

    async setup() {
        syncToBackend("default_rng_mode", app.ui.settings.getSettingValue(SETTING_RNG, "Signature"));
        syncToBackend("search_depth_limit", app.ui.settings.getSettingValue(SETTING_DEPTH, 80));
        syncToBackend("hide_comments", app.ui.settings.getSettingValue(SETTING_COMMENTS, true));
    }
});