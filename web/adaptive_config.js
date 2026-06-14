import { app } from "../../scripts/app.js";
import { api } from "../../scripts/api.js";

const ID_PREFIX = "AdaptivePrompts.";
const SETTING_DEPTH = ID_PREFIX + "search_depth_limit";
const SETTING_BFS = ID_PREFIX + "enable_bfs";
const SETTING_RNG = ID_PREFIX + "default_rng_mode";
const SETTING_COMMENTS = ID_PREFIX + "hide_comments";
const SETTING_RESOLUTION = ID_PREFIX + "resolution_strategy";
const SETTING_MISSING = ID_PREFIX + "missing_wildcard_behavior";

// Python Synchronization Hook
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

// Extension Registration
app.registerExtension({
    name: "AdaptivePrompts.Settings",

    settings: [
        {
            id: SETTING_RNG,
            name: "Default RNG Mode",
            type: "combo",
            options: ["Adaptive", "Legacy"],
            tooltip: "Adaptive: Identity-based RNG (rearrangeable prompts). Legacy: Sequential RNG (domino-effect).",
            defaultValue: "Adaptive",
            category: ["Adaptive Prompts", "Generation", "Default RNG Mode"],
            onChange: (value) => syncToBackend("default_rng_mode", value)
        },
        {
            id: SETTING_RESOLUTION,
            name: "BFS Resolution Strategy",
            type: "combo",
            options: ["Scoped", "Aggressive"],
            tooltip: "Scoped: This limits BFS from searching beyond the current scope. Aggressive: Resolve wildcards with full BFS.",
            defaultValue: "Scoped",
            category: ["Adaptive Prompts", "Resolution", "Resolution Strategy"],
            onChange: (value) => syncToBackend("resolution_strategy", value)
        },
        {
            id: SETTING_DEPTH,
            name: "Search Depth Limit",
            type: "slider",
            attrs: { min: 10, max: 200, step: 1 },
            defaultValue: 80,
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
        },
        {
            id: SETTING_MISSING,
            name: "Missing Wildcard Behavior",
            type: "combo",
            options: ["Inject Warning", "Silently Fail"],
            defaultValue: "Inject Warning",
            category: ["Adaptive Prompts", "Resolution", "Error Handling"],
            onChange: (value) => syncToBackend("missing_wildcard_behavior", value)
        },
    ],

    async setup() {
        syncToBackend("default_rng_mode", app.ui.settings.getSettingValue(SETTING_RNG, "Signature"));
        syncToBackend("search_depth_limit", app.ui.settings.getSettingValue(SETTING_DEPTH, 80));
        syncToBackend("hide_comments", app.ui.settings.getSettingValue(SETTING_COMMENTS, true));
        syncToBackend("resolution_strategy", app.ui.settings.getSettingValue(SETTING_RESOLUTION, "Scoped"));
        syncToBackend("missing_wildcard_behavior", app.ui.settings.getSettingValue(SETTING_MISSING, "Inject Warning"));
    }
});