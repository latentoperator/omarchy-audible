.pragma library
.import "Library.js" as Library
.import "Playback.js" as Playback

// Pure StateStore transitions (ARCHITECTURE 4.8). Effects are: backup(path,
// destination), write(text), save_now, retry_read, retry_backup, and wait_file.
// The QML owner performs those effects and feeds their results back as events.
function createState(path) {
  return {
    "path": _store.string(path),
    "doc": Library.parseState(""),
    "loaded": false,
    "dirty": false,
    "pendingOps": [],
    "lastError": "",
    "adoptWaiting": null
  };
}

function step(state, event) {
  var current = _store.cleanState(state);
  if (!_store.isObject(event)) return _store.result(current, []);
  var type = event.type;
  if (type === "adopt") return _store.adopt(current, event.text, event.path);
  if (type === "load_failed") {
    if (event.notFound === true) return _store.adopt(current, "", event.path);
    current.lastError = "could not read state.json";
    return _store.result(current, [{ "type": "retry_read" }]);
  }
  if (type === "backup_result") {
    if (event.code === 0 && current.adoptWaiting !== null) {
      var waiting = current.adoptWaiting;
      current.adoptWaiting = null;
      return _store.finishAdopt(current, waiting);
    }
    if (current.adoptWaiting === null) return _store.result(current, []);
    current.lastError = "could not back up the unreadable state.json";
    return _store.result(current, [{ "type": "retry_backup" }]);
  }
  if (type === "retry_backup") {
    if (current.adoptWaiting === null || current.path.length === 0) return _store.result(current, []);
    return _store.result(current, [_store.backupEffect(current.path)]);
  }
  if (type === "record" || type === "finished") {
    var op = type === "record"
      ? { "kind": "record", "asin": event.asin, "ms": event.ms, "at": event.at }
      : { "kind": "finished", "asin": event.asin };
    if (!current.loaded) {
      current.pendingOps.push(op);
      return _store.result(current, []);
    }
    _store.applyOp(current, op);
    return _store.result(current, []);
  }
  if (type === "set_queue") {
    if (!current.loaded) return _store.result(current, []);
    current.doc = Playback.withQueue(current.doc, event.queue);
    current.dirty = true;
    return _store.save(current);
  }
  if (type === "set_player_settings") {
    if (!current.loaded) return _store.result(current, []);
    var settings = Playback.withPlayerSettings(current.doc, event.volume, event.speed);
    if (settings === current.doc) return _store.result(current, []);
    current.doc = settings;
    current.dirty = true;
    return _store.save(current);
  }
  if (type === "save") return _store.save(current);
  if (type === "saved") {
    current.lastError = "";
    return _store.result(current, []);
  }
  if (type === "save_failed") {
    current.dirty = true;
    current.lastError = "could not save state.json";
    return _store.result(current, []);
  }
  if (type === "flush") {
    var saved = _store.save(current);
    return _store.result(saved.state, saved.effects.concat([{ "type": "wait_file" }]));
  }
  if (type === "path_changed") {
    current.path = _store.string(event.path);
    return _store.result(current, []);
  }
  return _store.result(current, []);
}

var _store = {};
_store.isObject = function (value) {
  return value !== null && value !== undefined && typeof value === "object" && !Array.isArray(value);
};
_store.string = function (value) { return typeof value === "string" ? value : ""; };
_store.result = function (state, effects) { return { "state": state, "effects": effects }; };
_store.cleanState = function (state) {
  var base = createState(_store.isObject(state) ? state.path : "");
  if (!_store.isObject(state)) return base;
  base.doc = _store.isObject(state.doc) ? state.doc : Library.parseState("");
  base.loaded = state.loaded === true;
  base.dirty = state.dirty === true;
  base.pendingOps = Array.isArray(state.pendingOps) ? state.pendingOps.slice() : [];
  base.lastError = _store.string(state.lastError);
  base.adoptWaiting = _store.isObject(state.adoptWaiting) ? state.adoptWaiting : null;
  return base;
};
_store.backupEffect = function (path) {
  return { "type": "backup", "path": path, "destination": path + ".corrupt" };
};
_store.adopt = function (state, text, path) {
  state.path = _store.string(path === undefined ? state.path : path);
  var source = typeof text === "string" ? text : "";
  var parsed = Library.parseState(source);
  if (source.length > 0 && parsed.recovered === true && state.path.length > 0) {
    state.adoptWaiting = parsed;
    return _store.result(state, [_store.backupEffect(state.path)]);
  }
  return _store.finishAdopt(state, parsed);
};
_store.finishAdopt = function (state, parsed) {
  state.doc = parsed;
  var ops = state.pendingOps;
  state.pendingOps = [];
  for (var i = 0; i < ops.length; i++) _store.applyOp(state, ops[i]);
  state.loaded = true;
  return _store.result(state, state.dirty ? [{ "type": "save_now" }] : []);
};
_store.applyOp = function (state, op) {
  if (!_store.isObject(op)) return;
  var next = op.kind === "finished"
    ? Playback.markFinished(state.doc, op.asin)
    : Playback.recordPosition(state.doc, op.asin, op.ms, op.at);
  if (next === state.doc) return;
  state.doc = next;
  state.dirty = true;
};
_store.save = function (state) {
  if (!state.loaded || !state.dirty || state.path.length === 0) return _store.result(state, []);
  state.dirty = false;
  return _store.result(state, [{ "type": "write", "text": Library.serializeState(state.doc) }]);
};
