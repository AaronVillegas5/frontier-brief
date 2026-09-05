/**
 * The Frontier Brief — Dashboard App
 *
 * Handles GitHub OAuth login, fetches the user's prefs.yaml from their
 * forked repository, populates the form, and commits updates back via
 * the GitHub Contents API.
 */

// -------------------------------------------------------------------------
// Configuration
// -------------------------------------------------------------------------
const CLIENT_ID = "Iv23lia9N65dm8Y9Tqpf";
const WORKER_URL = "https://frontier-brief-oauth.aaronvillegas5.workers.dev";
const REPO_NAME = "frontier-brief";
const PREFS_PATH = "prefs.yaml";

// -------------------------------------------------------------------------
// State
// -------------------------------------------------------------------------
let accessToken = null;
let currentUser = null;
let prefsSha = null; // Required by GitHub API to update a file

// -------------------------------------------------------------------------
// DOM References
// -------------------------------------------------------------------------
const loginSection = document.getElementById("login-section");
const configSection = document.getElementById("config-section");
const loginBtn = document.getElementById("login-btn");
const logoutBtn = document.getElementById("logout-btn");
const saveBtn = document.getElementById("save-btn");
const statusEl = document.getElementById("status");
const usernameEl = document.getElementById("username");

// -------------------------------------------------------------------------
// OAuth Flow
// -------------------------------------------------------------------------

// Step 1: Redirect to GitHub for authorization
loginBtn.addEventListener("click", (e) => {
  e.preventDefault();
  const redirectUri = window.location.href.split("?")[0]; // Current page without query params
  const scope = "public_repo"; // Only access to public repositories
  window.location.href =
    `https://github.com/login/oauth/authorize?client_id=${CLIENT_ID}&redirect_uri=${encodeURIComponent(redirectUri)}&scope=${scope}`;
});

// Step 2: Check if we're returning from GitHub with a code
async function handleOAuthCallback() {
  const params = new URLSearchParams(window.location.search);
  const code = params.get("code");

  if (code) {
    // Clean the URL so the code doesn't linger
    window.history.replaceState({}, document.title, window.location.pathname);

    showStatus("Signing in...", "loading");

    try {
      // Exchange code for token via our secure Cloudflare Worker
      const response = await fetch(WORKER_URL, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ code }),
      });

      const data = await response.json();

      if (data.access_token) {
        accessToken = data.access_token;
        sessionStorage.setItem("gh_token", accessToken);
        await initDashboard();
      } else {
        showStatus("Login failed: " + (data.error_description || "Unknown error"), "error");
      }
    } catch (err) {
      showStatus("Could not connect to authentication server.", "error");
    }
  }
}

// Check for saved session
function checkSession() {
  const saved = sessionStorage.getItem("gh_token");
  if (saved) {
    accessToken = saved;
    initDashboard();
    return true;
  }
  return false;
}

// Logout
logoutBtn.addEventListener("click", (e) => {
  e.preventDefault();
  sessionStorage.removeItem("gh_token");
  accessToken = null;
  currentUser = null;
  loginSection.style.display = "block";
  configSection.style.display = "none";
  hideStatus();
});

// -------------------------------------------------------------------------
// Dashboard Initialization
// -------------------------------------------------------------------------

async function initDashboard() {
  try {
    // Get current user
    const userRes = await ghApi("https://api.github.com/user");
    currentUser = userRes.login;
    usernameEl.textContent = currentUser;

    // Switch to config view
    loginSection.style.display = "none";
    configSection.style.display = "block";

    // Load their prefs.yaml
    await loadPrefs();
    hideStatus();
  } catch (err) {
    showStatus("Session expired. Please sign in again.", "error");
    sessionStorage.removeItem("gh_token");
    loginSection.style.display = "block";
    configSection.style.display = "none";
  }
}

// -------------------------------------------------------------------------
// GitHub API Helpers
// -------------------------------------------------------------------------

async function ghApi(url, options = {}) {
  const res = await fetch(url, {
    ...options,
    headers: {
      Authorization: `Bearer ${accessToken}`,
      Accept: "application/vnd.github.v3+json",
      ...(options.headers || {}),
    },
  });
  if (!res.ok) throw new Error(`GitHub API error: ${res.status}`);
  return res.json();
}

// -------------------------------------------------------------------------
// Load Prefs from User's Fork
// -------------------------------------------------------------------------

async function loadPrefs() {
  showStatus("Loading your settings...", "loading");

  try {
    const data = await ghApi(
      `https://api.github.com/repos/${currentUser}/${REPO_NAME}/contents/${PREFS_PATH}`
    );

    prefsSha = data.sha;
    const content = atob(data.content.replace(/\n/g, ""));
    const prefs = parseYaml(content);

    populateForm(prefs);
  } catch (err) {
    if (err.message.includes("404")) {
      showStatus(
        "Could not find prefs.yaml. Make sure you have forked the frontier-brief repository.",
        "error"
      );
    } else {
      showStatus("Error loading settings: " + err.message, "error");
    }
  }
}

// -------------------------------------------------------------------------
// Simple YAML Parser (handles our flat prefs.yaml structure)
// -------------------------------------------------------------------------

function parseYaml(text) {
  const result = {};
  let currentKey = null;
  let currentList = null;

  for (const line of text.split("\n")) {
    const trimmed = line.trim();

    // Skip comments and empty lines
    if (!trimmed || trimmed.startsWith("#")) continue;

    // List item
    if (trimmed.startsWith("- ") && currentKey) {
      if (!currentList) currentList = [];
      currentList.push(trimmed.slice(2).trim());
      continue;
    }

    // Save previous list if any
    if (currentKey && currentList) {
      result[currentKey] = currentList;
      currentList = null;
    }

    // Key: value pair
    const match = trimmed.match(/^([a-z_]+)\s*:\s*(.*)$/);
    if (match) {
      currentKey = match[1];
      const val = match[2].trim();

      if (val === "[]") {
        result[currentKey] = [];
        currentKey = null;
      } else if (val === "" || val === "~" || val === "null") {
        // Might be a list below
        currentList = [];
      } else {
        // Scalar value
        result[currentKey] = val.replace(/^["']|["']$/g, "");
        currentKey = null;
      }
    }
  }

  // Save last list
  if (currentKey && currentList) {
    result[currentKey] = currentList;
  }

  return result;
}

// -------------------------------------------------------------------------
// Serialize back to YAML
// -------------------------------------------------------------------------

function serializeYaml(prefs) {
  let yaml = "# The Frontier Brief — Personalization Preferences\n";
  yaml += "# Updated via Dashboard\n\n";

  // Topic focus
  yaml += "topic_focus:\n";
  for (const t of prefs.topic_focus || []) {
    yaml += `  - ${t}\n`;
  }
  yaml += "\n";

  // Preferred sources
  if ((prefs.preferred_sources || []).length > 0) {
    yaml += "preferred_sources:\n";
    for (const s of prefs.preferred_sources) {
      yaml += `  - ${s}\n`;
    }
  } else {
    yaml += "preferred_sources: []\n";
  }
  yaml += "\n";

  // Excluded sources
  if ((prefs.excluded_sources || []).length > 0) {
    yaml += "excluded_sources:\n";
    for (const s of prefs.excluded_sources) {
      yaml += `  - ${s}\n`;
    }
  } else {
    yaml += "excluded_sources: []\n";
  }
  yaml += "\n";

  // Scalars
  yaml += `frontier_watch_count: ${prefs.frontier_watch_count || 3}\n`;
  yaml += `hot_takes_count: ${prefs.hot_takes_count || 3}\n\n`;
  yaml += `audience: "${prefs.audience || "non-technical business owner"}"\n\n`;
  yaml += `tracking_pixel_url: "${prefs.tracking_pixel_url || ""}"\n\n`;
  yaml += `allow_telemetry: ${prefs.allow_telemetry}\n`;

  return yaml;
}

// -------------------------------------------------------------------------
// Form Population
// -------------------------------------------------------------------------

function populateForm(prefs) {
  // Topics
  const topics = prefs.topic_focus || [];
  document.querySelectorAll("#topics input").forEach((cb) => {
    cb.checked = topics.includes(cb.value);
  });

  // Audience
  const audienceSelect = document.getElementById("audience");
  if (prefs.audience) {
    audienceSelect.value = prefs.audience;
  }

  // Preferred sources
  const preferred = prefs.preferred_sources || [];
  document.querySelectorAll("#preferred-sources input").forEach((cb) => {
    cb.checked = preferred.includes(cb.value);
  });

  // Excluded sources
  const excluded = prefs.excluded_sources || [];
  document.querySelectorAll("#excluded-sources input").forEach((cb) => {
    cb.checked = excluded.includes(cb.value);
  });

  // Telemetry toggle
  document.getElementById("telemetry").checked =
    prefs.allow_telemetry !== "false" && prefs.allow_telemetry !== false;
}

// -------------------------------------------------------------------------
// Save Settings
// -------------------------------------------------------------------------

saveBtn.addEventListener("click", async () => {
  saveBtn.disabled = true;
  showStatus("Saving settings...", "loading");

  // Gather form state
  const prefs = {
    topic_focus: getCheckedValues("#topics"),
    preferred_sources: getCheckedValues("#preferred-sources"),
    excluded_sources: getCheckedValues("#excluded-sources"),
    frontier_watch_count: 3,
    hot_takes_count: 3,
    audience: document.getElementById("audience").value,
    tracking_pixel_url: "",  // Preserved from original — not editable in UI
    allow_telemetry: document.getElementById("telemetry").checked,
  };

  const yamlContent = serializeYaml(prefs);
  const encoded = btoa(unescape(encodeURIComponent(yamlContent)));

  try {
    await ghApi(
      `https://api.github.com/repos/${currentUser}/${REPO_NAME}/contents/${PREFS_PATH}`,
      {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          message: "chore: update preferences via dashboard",
          content: encoded,
          sha: prefsSha,
        }),
      }
    );

    showStatus("✓ Settings saved! Changes will take effect on the next daily run.", "success");

    // Refresh sha for future saves
    const refreshed = await ghApi(
      `https://api.github.com/repos/${currentUser}/${REPO_NAME}/contents/${PREFS_PATH}`
    );
    prefsSha = refreshed.sha;
  } catch (err) {
    showStatus("Failed to save: " + err.message, "error");
  } finally {
    saveBtn.disabled = false;
  }
});

function getCheckedValues(selector) {
  return Array.from(document.querySelectorAll(`${selector} input:checked`)).map(
    (cb) => cb.value
  );
}

// -------------------------------------------------------------------------
// Status Helpers
// -------------------------------------------------------------------------

function showStatus(msg, type) {
  statusEl.textContent = msg;
  statusEl.className = `status ${type}`;
}

function hideStatus() {
  statusEl.className = "status";
  statusEl.textContent = "";
}

// -------------------------------------------------------------------------
// Boot
// -------------------------------------------------------------------------

if (!checkSession()) {
  handleOAuthCallback();
}
