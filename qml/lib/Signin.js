.pragma library

// Onboarding view decisions that `Onboarding.js` does not make (U3): the step
// while reconnecting, where the Connect step is (pick a store, waiting for
// the sign-in link, paste, finishing), setup progress text, the account line,
// which jobs belong to onboarding, and what the event log may record for
// them. Pure ECMAScript for the Qt JS engine: no imports, no Qt types, and
// nothing here throws on bad input. Nothing here ever receives the pasted
// text.

// Connect phases.
var PHASE_PICK = "pick";
var PHASE_STARTING = "starting";
var PHASE_PASTE = "paste";
var PHASE_FINISHING = "finishing";

// Shown when the pasted text has no one-time code (FR-A1); it is not sent.
var BAD_PASTE = "That doesn't look like the Amazon page address";

// The confirm question for Disconnect (FR-A3).
var DISCONNECT_QUESTION = "Disconnect Audible? Downloaded books stay on this laptop.";

// The default store (ARCHITECTURE 4.7).
var DEFAULT_MARKETPLACE = "us";

// Backend commands the onboarding view runs. Their events are logged by type
// only: the sign-in link and session never reach `recentEvents`.
var COMMANDS = ["setup", "login-start", "login-finish", "login-import-cli", "logout"];

// Commands after which `status` is read again.
var REFRESH_STATUS = ["setup", "login-finish", "login-import-cli", "logout"];

// Sign-in commands: a success ends reconnecting and runs the first sync.
var SIGN_IN = ["login-finish", "login-import-cli"];

function _has(list, item) {
  return Array.isArray(list) && list.indexOf(item) >= 0;
}

// The step to show: Reconnect (after `auth_failed`) reopens Connect even
// while `status` still says signed in.
function effectiveStep(step, reconnecting) {
  if (step === "ready" && reconnecting === true) return "connect";
  return typeof step === "string" && step.length > 0 ? step : "loading";
}

// Where the Connect step is: finishing (login-finish queued or running),
// paste (a sign-in session is open), starting (login-start running), else
// pick a store.
function phase(session, starting, finishing) {
  if (finishing === true) return PHASE_FINISHING;
  if (typeof session === "string" && session.length > 0) return PHASE_PASTE;
  if (starting === true) return PHASE_STARTING;
  return PHASE_PICK;
}

function isOnboardingCommand(command) {
  return _has(COMMANDS, command);
}

function refreshesStatus(command) {
  return _has(REFRESH_STATUS, command);
}

function isSignIn(command) {
  return _has(SIGN_IN, command);
}

// Whether `command` is queued or running in the job runner.
function jobPending(command, pending, active) {
  if (active && active.command === command) return true;
  if (!Array.isArray(pending)) return false;
  for (var i = 0; i < pending.length; i++) {
    if (pending[i] && pending[i].command === command) return true;
  }
  return false;
}

// The event-log line for a backend event: onboarding commands log only the
// event type; everything else logs the summary the caller made.
function logText(command, type, summary) {
  if (isOnboardingCommand(command)) return typeof type === "string" ? type : "event";
  return typeof summary === "string" ? summary : "";
}

// Setup progress, from a `progress` event: "Setting up (2 of 4): requirements".
function setupText(progress) {
  if (!progress || typeof progress !== "object" || typeof progress.stage !== "string") return "Setting up…";
  var n = progress.n;
  var of = progress.of;
  if (typeof n === "number" && typeof of === "number" && of > 0) {
    return "Setting up (" + n + " of " + of + "): " + progress.stage;
  }
  return "Setting up: " + progress.stage;
}

// The store's label from `Onboarding.marketplaces()`, else the code.
function marketplaceLabel(code, list) {
  if (typeof code !== "string" || code.length === 0) return "";
  if (Array.isArray(list)) {
    for (var i = 0; i < list.length; i++) {
      if (list[i] && list[i].code === code && typeof list[i].label === "string") return list[i].label;
    }
  }
  return code;
}

// The account row: "Chris · United States", or "Signed in · United States"
// when `status.account` is null.
function accountLine(account, marketplaceText) {
  var who = typeof account === "string" && account.trim().length > 0 ? account.trim() : "Signed in";
  var where = typeof marketplaceText === "string" && marketplaceText.length > 0 ? marketplaceText : "";
  return where.length > 0 ? who + " · " + where : who;
}

// Whether a job outcome means the credentials are gone (FR-A4).
function authFailed(outcome) {
  return !!outcome && outcome.ok !== true && outcome.code === "auth_failed";
}

// `Onboarding.marketplaces()` as Dropdown options `[{value, label}]`.
function storeOptions(list) {
  var out = [];
  if (!Array.isArray(list)) return out;
  for (var i = 0; i < list.length; i++) {
    var item = list[i];
    if (item && typeof item.code === "string" && item.code.length > 0) {
      out.push({ "value": item.code, "label": typeof item.label === "string" ? item.label : item.code });
    }
  }
  return out;
}

// The onboarding view's heading.
function heading(step, reconnecting) {
  if (step === "missing") return "A few tools are missing";
  if (step === "setup") return "Set up Omarchy Audible";
  if (step === "connect") return reconnecting === true ? "Reconnect Audible" : "Connect Audible";
  return "Checking your setup…";
}

// The setup line: progress while setup runs, else what it does.
function setupLine(running, progress) {
  return running === true ? setupText(progress) : "Installs the Audible support the plugin needs. It takes about a minute.";
}

// The waiting line for the starting and finishing phases, else "".
function phaseText(phase) {
  if (phase === PHASE_STARTING) return "Opening the Amazon sign-in page…";
  if (phase === PHASE_FINISHING) return "Connecting…";
  return "";
}
