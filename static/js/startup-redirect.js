const POLL_INTERVAL_MS = 1000;
const APP_URL = "http://127.0.0.1:8000/app";

async function isOrchestratorUp() {
  try {
    const response = await fetch("http://127.0.0.1:8000/engine/status");
    return response.ok;
  } catch {
    return false;
  }
}

async function waitAndRedirect() {
  while (!(await isOrchestratorUp())) {
    await new Promise((resolve) => setTimeout(resolve, POLL_INTERVAL_MS));
  }
  window.location.replace(APP_URL);
}

waitAndRedirect();
