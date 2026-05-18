/** Fixed ports for the E2E transaction WS bridge (must match playwright webServer + globalSetup). */
export const BRIDGE_WS_PORT = 47999;
export const BRIDGE_HTTP_PORT = 47998;
export const BRIDGE_WS_URL = `ws://127.0.0.1:${BRIDGE_WS_PORT}`;
export const BRIDGE_PUSH_URL = `http://127.0.0.1:${BRIDGE_HTTP_PORT}/push`;
