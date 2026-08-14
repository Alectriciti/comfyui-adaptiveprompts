import { app } from "../../scripts/app.js";

function openWildcardManager() {
    window.open(`${window.location.origin}/adaptiveprompts`, "_blank");
}

app.registerExtension({
    name: "AdaptivePrompts.WildcardManagerButton",
    actionBarButtons: [
        {
            icon: "pi pi-images",
            tooltip: "Open Wildcard Manager",
            onClick: openWildcardManager,
        },
    ],
});