const POLL_INTERVAL_MS = 2000;

async function isEngineReady() {
  try {
    const response = await fetch("/engine/status");
    if (!response.ok) return false;
    const data = await response.json();
    return data.ready === true;
  } catch {
    return false;
  }
}

async function waitForEngine() {
  const overlay = document.getElementById("engine-loading-overlay");
  if (!overlay) return;

  while (!(await isEngineReady())) {
    await new Promise((resolve) => setTimeout(resolve, POLL_INTERVAL_MS));
  }

  overlay.hidden = true;
}

waitForEngine();
