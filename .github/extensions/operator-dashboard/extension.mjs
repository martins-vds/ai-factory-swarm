import { CanvasError, createCanvas, joinSession } from "@github/copilot-sdk/extension";
import { startServer } from "./server.mjs";

const servers = new Map();
await joinSession({
    canvases: [createCanvas({
        id: "operator-dashboard",
        displayName: "Operator dashboard",
        description: "Read-only view of operator needs, Copilot sessions, and eval evidence.",
        inputSchema: { type: "object", additionalProperties: false },
        actions: [{
            name: "dataset_status",
            description: "Read dataset source, freshness, and row counts.",
            async handler({ instanceId }) {
                const entry = servers.get(instanceId);
                if (!entry) throw new CanvasError("not_open", "The dashboard is not open.");
                return (await entry).status();
            },
        }],
        async open({ instanceId }) {
            if (!servers.has(instanceId)) servers.set(instanceId, startServer());
            try {
                return { title: "Operator dashboard", url: (await servers.get(instanceId)).url };
            } catch (error) {
                servers.delete(instanceId);
                throw error;
            }
        },
        async onClose({ instanceId }) {
            const entry = servers.get(instanceId);
            servers.delete(instanceId);
            if (entry) (await entry).server.close();
        },
    })],
});
