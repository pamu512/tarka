--[[
Prune **stale** velocity counters using **SCAN** (never KEYS) + ``OBJECT IDLETIME``.

Deletes keys whose **idle time** (seconds since last read/write) is **>= idle_threshold_sec**.
The caller **must** pass ``idle_threshold_sec`` (no implicit 24-hour default — configure via
``REDIS_VELOCITY_PRUNE_IDLE_SEC`` / ``DeploymentRuntimeSettings`` in ``run_prune_velocity.py``).

**Patterns** (run separately if needed):
  - Signal API: ``velocity:*``
  - Anumana: ``anumana:velocity:*``

This does **not** match ``seen:*``, ``session:*``, ``signal:*`` when you use the narrow patterns above.

Usage (zero KEYS, all ARGV after comma)::

    redis-cli --eval scripts/redis/prune_velocity.lua , 'velocity:*' 86400 200 100 0

Returns **3** values: ``next_cursor``, ``deleted``, ``keys_examined_this_call`` (then re-invoke with
``next_cursor`` until ``0``).

ARGV:
  1. ``MATCH`` glob (default caller should pass ``velocity:*`` or ``anumana:velocity:*``)
  2. ``idle_threshold_sec`` (**required** — seconds of idle time before DELETE)
  3. ``max_scan_rounds`` per EVAL (caps server blocking; default 200)
  4. ``SCAN COUNT`` hint (default 100)
  5. ``cursor`` start (``0``)

Safety: only keys matched by ``MATCH`` are considered; session / seen keys are untouched if they do
not match the velocity glob.
--]]

local pattern = ARGV[1]
if pattern == nil or pattern == "" then
  return redis.error_reply("ARGV[1] MATCH pattern is required (e.g. velocity:*)")
end

local idle_threshold = tonumber(ARGV[2])
if idle_threshold == nil then
  return redis.error_reply(
    "ARGV[2] idle_threshold_sec is required (configure REDIS_VELOCITY_PRUNE_IDLE_SEC / REDIS_VELOCITY_TTL)"
  )
end
local max_scan_rounds = tonumber(ARGV[3]) or 200
local scan_count = tonumber(ARGV[4]) or 100
local cursor = ARGV[5] or "0"

if idle_threshold < 1 then
  return redis.error_reply("idle_threshold_sec must be >= 1")
end
if max_scan_rounds < 1 then
  return redis.error_reply("max_scan_rounds must be >= 1")
end
if scan_count < 1 then
  return redis.error_reply("scan_count must be >= 1")
end

local function scan_cursor_done(c)
  return tostring(c) == "0"
end

local deleted = 0
local examined = 0
local rounds = 0

repeat
  local scan_result = redis.call("SCAN", cursor, "MATCH", pattern, "COUNT", scan_count)
  cursor = scan_result[1]
  local keys = scan_result[2]
  for i = 1, #keys do
    examined = examined + 1
    local k = keys[i]
    local idle = redis.call("OBJECT", "IDLETIME", k)
    if idle ~= nil and idle ~= false then
      local idle_n = tonumber(idle)
      if idle_n ~= nil and idle_n >= idle_threshold then
        redis.call("DEL", k)
        deleted = deleted + 1
      end
    end
  end
  rounds = rounds + 1
  if rounds >= max_scan_rounds then
    break
  end
until scan_cursor_done(cursor)

return { tostring(cursor), deleted, examined }
