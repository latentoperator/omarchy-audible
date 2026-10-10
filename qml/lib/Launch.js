.pragma library

// How a backend command is launched without an ASIN on its command line.
//
// A process's argv is readable by every local user through /proc/<pid>/cmdline,
// and an ASIN names the book. So the shell keeps a job's ASINs in its `args`
// (the queue, the drawer and the removal list match on them) but `split`
// takes them out at spawn time; `environment` hands them to the backend in
// OMARCHY_AUDIBLE_ASIN, which only the same user can read. The backend puts
// them back in front of the remaining arguments (backend/omarchy_audible/cli.py),
// so `omarchy-audible get <asin>` still works by hand.
//
// Pure ECMAScript for the Qt JS engine: no imports, no Qt types, and nothing
// here throws on bad input.

var ASIN_ENV = "OMARCHY_AUDIBLE_ASIN";

// Commands whose first argument is one ASIN. `position-get` takes several and
// fake mode's `sync --fake-hide` one; the backend keeps the same lists
// (backend/omarchy_audible/cli.py).
var SINGLE_ASIN_COMMANDS = ["get", "remove", "cancel", "play-info", "position-push"];
// Flags of those commands whose next token is their value, not an ASIN.
var VALUE_FLAGS = ["--fake-fail", "--fake-chapters", "--at"];

function isFlag(token) {
  return typeof token === "string" && token.charAt(0) === "-";
}

// `{args, asins}`: the arguments that may go on the command line, and the
// ASINs that must not.
function split(command, args) {
  var list = Array.isArray(args) ? args.map(function(token) { return String(token) }) : [];
  var asins = [];
  var rest = [];
  if (command === "position-get") {
    // `position-get <asin> [<asin> ...]`.
    for (var i = 0; i < list.length; i++) {
      if (isFlag(list[i])) rest.push(list[i]);
      else asins.push(list[i]);
    }
  } else if (command === "sync") {
    // Fake mode's `sync --fake-hide <asin>`; the backend adds the flag back
    // in front of the ASIN it reads from the environment.
    for (var j = 0; j < list.length; j++) {
      if (list[j] === "--fake-hide" && j + 1 < list.length && !isFlag(list[j + 1])) {
        asins.push(list[j + 1]);
        j += 1;
      } else {
        rest.push(list[j]);
      }
    }
  } else if (SINGLE_ASIN_COMMANDS.indexOf(command) !== -1) {
    // The first positional argument, wherever it is; the backend puts it back
    // in front, where every one of these commands reads it.
    for (var k = 0; k < list.length; k++) {
      if (asins.length === 0 && !isFlag(list[k])) {
        asins.push(list[k]);
        continue;
      }
      rest.push(list[k]);
      if (VALUE_FLAGS.indexOf(list[k]) !== -1 && k + 1 < list.length) {
        rest.push(list[k + 1]);
        k += 1;
      }
    }
  } else {
    rest = list;
  }
  return { "args": rest, "asins": asins };
}

// A copy of `base` with the ASINs added, space-separated. With no ASINs the
// variable is left out.
function environment(base, asins) {
  var env = {};
  if (base !== null && typeof base === "object") {
    for (var name in base) {
      if (Object.prototype.hasOwnProperty.call(base, name)) env[name] = base[name];
    }
  }
  if (Array.isArray(asins) && asins.length > 0) env[ASIN_ENV] = asins.join(" ");
  return env;
}
