import { app } from "../../scripts/app.js";

const BUTTON_TOOLTIP = "Wildcard Manager";

function openWildcardManager() {
    window.open(`${window.location.origin}/adaptiveprompts`, "_blank");
}

app.registerExtension({
    name: "AdaptivePrompts.WildcardManagerButton",
    actionBarButtons: [
        {
            icon: "pi pi-id-card",
            tooltip: BUTTON_TOOLTIP,
            onClick: openWildcardManager,
        },
    ],

    async setup() {
        const styleId = "adaptiveprompts-wildcard-manager-style";

        if (document.getElementById(styleId)) {
            return;
        }

        const style = document.createElement("style");
        style.id = styleId;

        style.textContent = `
        button:has(> i.pi-id-card) {
            background-color: rgb(63, 138, 46) !important;
            border-radius: 6px !important;
        }

        /* The icon itself */
        button:has(> i.pi-id-card) > i.pi-id-card {
            color: #c5f3b3 !important;
        }

        button:has(> i.pi-id-card):hover {
            filter: brightness(1.15);
        }
    `;

        document.head.appendChild(style);
    }
});