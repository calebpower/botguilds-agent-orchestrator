// BotGuilds web UI: canvas tile renderer + three SSE-fed views.
// Spectate is display-only; player and guild views need the guild cookie.

const TILE = 16;
let COLS = 32;               // atlas geometry; corrected from /api/tiles on boot
let COUNT = Infinity;        // base atlas tile count; indices past it live on the gen sheet
const FOCUS_GRACE = 20;   // ticks a followed character may be absent before we give up on them
// item tag coloured by its registry type (weapon, consumable, outfit, …);
// pass the item dict to get a tier star prefix and a hover description
const itemTag = (kind, label = kind, item = null) => {
  const stars = item && item.tier >= 2 ? "★".repeat(item.tier - 1) + " " : "";
  const title = item && item.desc ? ` title="${item.desc.replace(/"/g, "&quot;")}"` : "";
  return `<span class="tag ${state.types[kind] || ""}"${title}>${stars}${label}</span>`;
};

const TIER_NAMES = ["crude", "sound", "fine", "masterwork"];
const BREW_TIER_NAMES = ["draught", "potion", "elixir", "grand"];

// the quality split under an item row; all-ordinary stock has nothing to add
function tierLine(kind, tiers) {
  if (tiers.size === 1 && tiers.has(1)) return "";
  const names = state.types[kind] === "consumable" ? BREW_TIER_NAMES : TIER_NAMES;
  return `<small class="sub">${[...tiers.entries()].sort((a, b) => a[0] - b[0])
    .map(([tier, n]) => `${names[tier] || `tier ${tier}`} ×${n}`)
    .join(", ")}</small>`;
}

// a pile of items as one row per kind, "vial_red ×3", quality broken out below
function countTags(items) {
  const groups = new Map();
  for (const item of items) {
    const group = groups.get(item.kind) || { item, n: 0, tiers: new Map() };
    group.n++;
    group.tiers.set(item.tier, (group.tiers.get(item.tier) || 0) + 1);
    groups.set(item.kind, group);
  }
  return [...groups.values()]
    .sort((a, b) => b.n - a.n || a.item.kind.localeCompare(b.item.kind))
    .map(({ item, n, tiers }) =>
      itemTag(item.kind, n > 1 ? `${item.kind} ×${n}` : item.kind, { desc: item.desc })
      + tierLine(item.kind, tiers))
    .join("") || "—";
}
const sheet = new Image();
sheet.src = "/assets/atlas.png";
const genSheet = new Image();
genSheet.src = "/assets/atlas_gen.png";
const hurtSheet = new Image();     // red-shifted base atlas, for damage flashes
hurtSheet.src = "/assets/atlas_hurt.png";
const inertSheet = new Image();    // desaturated base atlas, for ground drops
inertSheet.src = "/assets/atlas_inert.png";
const SHEETS = { base: sheet, hurt: hurtSheet, inert: inertSheet };
const genHurtSheet = new Image();  // gen sheet with registry tiles red-shifted
genHurtSheet.src = "/assets/atlas_gen_hurt.png";
const genInertSheet = new Image(); // gen sheet with outfit tiles desaturated
genInertSheet.src = "/assets/atlas_gen_inert.png";
const GEN_SHEETS = { base: genSheet, hurt: genHurtSheet, inert: genInertSheet };

// The server only serves sprite indices for kinds we can name (/api/tiles?kinds=…),
// so we request them as frames reveal them. Unknown kinds draw as bareTile for a
// frame or two until the fetch lands.
const KIND_KEYS = new Set(["kind", "kind_name", "outfit", "held", "hand", "offhand",
                           "trinket", "boots"]);
const askedKinds = new Set();
function collectKinds(node, out) {
  if (Array.isArray(node)) { for (const v of node) collectKinds(v, out); return; }
  if (!node || typeof node !== "object") return;
  for (const [key, value] of Object.entries(node)) {
    if (typeof value === "string" && KIND_KEYS.has(key)) out.add(value);
    else collectKinds(value, out);
  }
}
function ensureSprites(data) {
  const seen = new Set();
  collectKinds(data, seen);
  const missing = [...seen].filter((k) => !askedKinds.has(k));
  if (!missing.length) return;
  for (const k of missing) askedKinds.add(k);
  fetch("/api/tiles?kinds=" + encodeURIComponent(missing.join(",")))
    .then((r) => r.json())
    .then((d) => {
      Object.assign(state.tiles, d.tiles);
      Object.assign(state.types, d.types);
      Object.assign(state.tierTiles, d.tier_tiles);
    });
}

const state = {
  tiles: {},             // item/monster kind -> spritesheet index
  fxTiles: {},           // effect sprites (arrow) for animations
  guildColors: {},       // guild_id -> player-chosen "#rrggbb"
  types: {},             // item kind -> registry type, for tag colours
  tierTiles: {},         // item kind -> [sprite per tier 0-3]
  surfaceTiles: {},      // surface kind (fire/rime) -> sprite index
  bareTile: 0,           // fallback sprite when a character has no look; set on boot
  looks: {},             // cosmetic look name -> spritesheet index
  follow: null,
  followChar: null,      // spectate: char_uid pinned to the selected map
  followCharName: null,
  center: null,
  spectateSource: null,
  meSource: null,
  lastMap: null,
  focus: null,           // char_uid the player view follows
  chars: new Map(),      // char_uid -> latest dict, across every world's frames
  village: null,
  maps: [],              // spectate map list, reused by the guild view filter
  guildFilter: "all",    // guild view: only chars in this world ("all" = everyone)
  log: [],
  zoom: TILE,            // pixels per tile; TILE is the spritesheet's native size
  showColors: true,      // draw guild-colour corner brackets under characters
  camMode: "smooth",     // "smooth" spring-pan | "lazy" deadband recenter | "instant"
};

const $ = (id) => document.getElementById(id);
const setStatus = (text) => { $("status").textContent = text; };

// --- guild colours ----------------------------------------------------------

// every guild has a colour before anyone picks one: hash into a fixed palette
const FALLBACK_COLORS = ["#e05d5d", "#5da9e0", "#69c25f", "#d8b13c",
                         "#b070e0", "#e0824f", "#4fc7b8", "#d16fae"];
function guildColor(id) {
  if (!id) return null;
  if (state.guildColors[id]) return state.guildColors[id];
  let h = 0;
  for (const c of id) h = (h * 31 + c.charCodeAt(0)) >>> 0;
  return FALLBACK_COLORS[h % FALLBACK_COLORS.length];
}

// --- animations -------------------------------------------------------------
// Short client-side effects built from each tick's events: melee lunges with a
// weapon thrust, projectiles, thrown items, AoE rings, death fades, and a
// position tween for anything that moved a step. Anything else stays silent.

const ANIM = { tween: 200, bump: 240, ring: 380, fade: 420,
               projPerTile: 45, projMin: 120 };
const MAGIC_BOLTS = { wand_orange: "#ff8c3b", wand_blue: "#5bd0e8",
                      wand_yellow: "#ffd94a", scepter_purple: "#b06df0" };
const CLOUD_COLORS = { poison: "#69c25f", sleep: "#5da9e0" };
const ESSENCE_COLORS = { ember: "#ff8c3b", frost: "#5bd0e8", venom: "#69c25f",
                         vigor: "#e05d5d", clarity: "#f0e6b2", aether: "#b06df0" };

function frameEntities(frame) {
  return frame.entities || (frame.visible && frame.visible.entities) || [];
}

function queueAnims(canvas, frame) {
  const now = performance.now();
  const anims = canvas._anims = (canvas._anims || []).filter((a) => now < a.start + a.dur);
  const byEid = new Map(frameEntities(frame).map((e) => [e.eid, e]));

  // movement: tween anyone whose tile changed since the last frame
  if (canvas._entWorld !== frame.world) canvas._entPos = null;
  canvas._entWorld = frame.world;
  const prev = canvas._entPos || new Map();
  const cur = new Map();
  for (const [eid, ent] of byEid) {
    cur.set(eid, ent.pos);
    const p = prev.get(eid);
    if (p && (p[0] !== ent.pos[0] || p[1] !== ent.pos[1]) &&
        Math.max(Math.abs(p[0] - ent.pos[0]), Math.abs(p[1] - ent.pos[1])) <= 2)
      anims.push({ kind: "tween", eid, from: p, to: ent.pos, start: now, dur: ANIM.tween });
  }
  canvas._entPos = cur;

  const bumped = new Set();                        // one lunge per cleave
  const proj = (from, to, extra) => anims.push({
    kind: "proj", from, to, start: now, ...extra,
    dur: Math.max(ANIM.projMin,
                  ANIM.projPerTile * Math.hypot(to[0] - from[0], to[1] - from[1]))});
  const ring = (pos, r, color, fill) =>
    anims.push({ kind: "ring", pos, r, color, fill, start: now, dur: ANIM.ring });

  for (const ev of frame.events || []) {
    const from = ev.from, to = ev.pos;
    switch (ev.kind) {
      case "attack": case "miss": {
        if (!from) break;
        const attacker = byEid.get(ev.attacker ?? ev.eid);
        const held = attacker && attacker.held;
        const dist = Math.max(Math.abs(to[0] - from[0]), Math.abs(to[1] - from[1]));
        if (ev.cause === "shoot" || (ev.kind === "miss" && dist > 1)) {
          const bolt = MAGIC_BOLTS[held] || (ev.magic ? "#b06df0" : null);
          proj(from, to, bolt ? { color: bolt } : { sprite: state.fxTiles.arrow });
        } else if (ev.kind === "miss" || ev.cause === "attack") {
          const eid = ev.attacker ?? ev.eid;
          if (bumped.has(eid)) break;
          bumped.add(eid);
          const swing = ["weapon", "tool"].includes(state.types[held])
            ? state.tiles[held] : undefined;
          anims.push({ kind: "bump", eid, from, to, start: now, dur: ANIM.bump,
                       weapon: swing });
        }
        break;
      }
      case "item_landed":
        if (from) proj(from, to, { sprite: state.tiles[ev.kind_name] });
        break;
      case "charge": case "ride":       // multi-tile rushes: one long tween
        if (ev.from)
          anims.push({ kind: "tween", eid: ev.eid, from: ev.from, to: ev.to,
                       start: now,
                       dur: ev.kind === "ride" ? ANIM.tween * 2 : ANIM.tween });
        break;
      case "blink":                     // vanish and reappear, marked both ends
        if (ev.from) ring(ev.from, 0.5, "#5bd0e8");
        ring(ev.to || ev.pos, 0.5, "#5bd0e8");
        break;
      case "bomb": ring(to, 1.5, "#e0824f"); break;
      case "blast": ring(to, 1.5, "#b06df0"); break;
      case "nova": ring(to, 2, "#ff8c3b"); break;
      case "cloud": ring(to, 1.5, CLOUD_COLORS[ev.status] || "#9aa7bb", true); break;
      case "spore_burst": ring(to, 1.5, "#69c25f", true); break;
      case "trap_fire": ring(to, 0.8, "#d16f5d"); break;
      case "warded": ring(to, 0.6, "#5da9e0"); break;
      case "cast_bolt":
        if (from) proj(from, to, { color: ESSENCE_COLORS[ev.essence] || "#b06df0" });
        break;
      case "veiled": case "attuned":
        ring(to, 0.6, ESSENCE_COLORS[ev.essence] || "#b06df0"); break;
      case "field": ring(to, 1.5, ESSENCE_COLORS[ev.essence] || "#b06df0", true); break;
      case "burst": ring(to, 2, ESSENCE_COLORS[ev.essence] || "#b06df0"); break;
      case "miscast": ring(to, 0.6, "#9aa7bb", true); break;
      case "purged": ring(to, 0.5, "#f0e6b2"); break;
      case "death": {
        const sprite = state.tiles[ev.kind_name];
        if (sprite !== undefined)
          anims.push({ kind: "fade", pos: to, sprite, start: now, dur: ANIM.fade });
        break;
      }
    }
  }
  if (anims.length) startAnimLoop();
}

let animRunning = false;
function startAnimLoop() {
  if (animRunning) return;
  animRunning = true;
  requestAnimationFrame(function step(now) {
    let live = false;
    for (const id of ["spectate-canvas", "player-canvas"]) {
      const canvas = $(id);
      if (!canvas || !canvas._frame) continue;
      const camActive = canvas._cam && !canvas._cam.settled;
      if (!(canvas._anims || []).length && !camActive) continue;
      canvas._anims = (canvas._anims || []).filter((a) => now < a.start + a.dur);
      drawFrame(canvas, canvas._frame);   // final draw settles everything in place
      live = live || canvas._anims.length > 0 || !canvas._cam.settled;
    }
    if (live) requestAnimationFrame(step);
    else animRunning = false;
  });
}

// entity draw offsets, in tile units, from the running tweens and lunges
function animOffsets(anims, now) {
  const offsets = new Map();
  for (const a of anims) {
    const t = Math.min(1, (now - a.start) / a.dur);
    if (a.kind === "tween")
      offsets.set(a.eid, [(a.from[0] - a.to[0]) * (1 - t),
                          (a.from[1] - a.to[1]) * (1 - t)]);
    else if (a.kind === "bump") {
      const s = Math.sin(Math.PI * t) * 0.3;
      offsets.set(a.eid, [Math.sign(a.to[0] - a.from[0]) * s,
                          Math.sign(a.to[1] - a.from[1]) * s]);
    }
  }
  return offsets;
}

// weapon and arrow art points up / north-east; rotate it to face the target
function drawSpriteRotated(ctx, index, cx, cy, size, angle) {
  ctx.save();
  ctx.translate(cx, cy);
  ctx.rotate(angle);
  drawSprite(ctx, index, -size / 2, -size / 2, size);
  ctx.restore();
}

function drawAnims(ctx, anims, now, px, py, size) {
  for (const a of anims) {
    const t = Math.min(1, (now - a.start) / a.dur);
    if (a.kind === "proj") {
      const x = a.from[0] + (a.to[0] - a.from[0]) * t;
      const y = a.from[1] + (a.to[1] - a.from[1]) * t;
      const cx = px(x) + size / 2, cy = py(y) + size / 2;
      const angle = Math.atan2(-(a.to[1] - a.from[1]), a.to[0] - a.from[0]);
      if (a.sprite !== undefined && a.sprite !== null)
        drawSpriteRotated(ctx, a.sprite, cx, cy, size * 0.8,
                          angle + (a.sprite === state.fxTiles.arrow ? Math.PI / 4 : 0));
      else {
        ctx.fillStyle = a.color || "#e8ecf4";
        ctx.beginPath();
        ctx.arc(cx, cy, Math.max(2, size * 0.16), 0, 7);
        ctx.fill();
      }
    } else if (a.kind === "bump" && a.weapon !== undefined) {
      const s = Math.sin(Math.PI * t);
      const dx = Math.sign(a.to[0] - a.from[0]), dy = Math.sign(a.to[1] - a.from[1]);
      const cx = px(a.from[0] + dx * (0.4 + 0.4 * s)) + size / 2;
      const cy = py(a.from[1] + dy * (0.4 + 0.4 * s)) + size / 2;
      drawSpriteRotated(ctx, a.weapon, cx, cy, size * 0.9,
                        Math.atan2(-dy, dx) + Math.PI / 2);
    } else if (a.kind === "ring") {
      const cx = px(a.pos[0]) + size / 2, cy = py(a.pos[1]) + size / 2;
      ctx.globalAlpha = 1 - t;
      if (a.fill) {
        ctx.fillStyle = a.color;
        ctx.beginPath();
        ctx.arc(cx, cy, (0.4 + a.r * t) * size, 0, 7);
        ctx.fill();
      } else {
        ctx.strokeStyle = a.color;
        ctx.lineWidth = Math.max(2, size / 6) * (1 - t * 0.7);
        ctx.beginPath();
        ctx.arc(cx, cy, (0.3 + a.r * t) * size, 0, 7);
        ctx.stroke();
      }
      ctx.globalAlpha = 1;
    } else if (a.kind === "fade") {
      ctx.globalAlpha = 1 - t;
      drawSprite(ctx, a.sprite, px(a.pos[0]), py(a.pos[1]), size, "inert");
      ctx.globalAlpha = 1;
    }
  }
}

// --- rendering --------------------------------------------------------------

function spriteFor(entity) {
  if (entity.kind === "char")
    return state.tiles[entity.outfit] ?? state.looks[entity.look] ?? state.bareTile;
  return state.tiles[entity.kind] ?? state.bareTile;
}

// variant: "base" | "hurt" | "inert". Indices past COUNT live on the gen sheet
// at index - COUNT; its variant sheets are full copies with only the relevant
// tiles transformed, so any gen index is safe under any variant.
function drawSprite(ctx, index, x, y, size, variant = "base") {
  let img = SHEETS[variant] || sheet;
  if (index >= COUNT) { img = GEN_SHEETS[variant] || genSheet; index -= COUNT; }
  const sx = (index % COLS) * TILE, sy = Math.floor(index / COLS) * TILE;
  ctx.drawImage(img, sx, sy, TILE, TILE, x, y, size, size);
}

// The tile the view is centred on. Anything derived from what is *visible* would
// drift as vision changes, so prefer the server's window, then the party.
function frameCenter(frame, tiles) {
  const focused = (frame.chars || []).find((c) => c.char_uid === state.focus && c.pos);
  if (focused) return focused.pos;
  if (frame.view) {
    const [vx0, vy0, vx1, vy1] = frame.view;
    return [(vx0 + vx1) / 2, (vy0 + vy1) / 2];
  }
  const placed = (frame.chars || []).filter((c) => c.pos);
  if (placed.length)
    return [placed.reduce((s, c) => s + c.pos[0], 0) / placed.length,
            placed.reduce((s, c) => s + c.pos[1], 0) / placed.length];
  let x0 = Infinity, y0 = Infinity, x1 = -Infinity, y1 = -Infinity;
  for (const [x, y] of tiles) {
    x0 = Math.min(x0, x); x1 = Math.max(x1, x);
    y0 = Math.min(y0, y); y1 = Math.max(y1, y);
  }
  return [(x0 + x1) / 2, (y0 + y1) / 2];
}

// --- camera -----------------------------------------------------------------
// The raw frame center jumps a whole tile per tick; the camera makes following
// watchable. "smooth" is a spring: displacement-weighted force, friction and
// inertia. "lazy" recenters only when the target leaves a zoom-based radius.

const CAM_SPRING = 40;     // force per tile of displacement (1/s^2)
const CAM_FRICTION = 10;   // velocity damping (1/s)
const CAM_STICTION = 2;    // "smoother": hold still until the target is this far
const CAM_SOFT = [12, 8];  // "smoother": gentler spring/friction once unstuck

function cameraCenter(canvas, frame, tiles, size, now) {
  const [tx, ty] = frameCenter(frame, tiles);
  let cam = canvas._cam;
  const viewR = Math.min(canvas.width, canvas.height) / size / 4;   // in tiles
  // first frame, map switch, or a cross-map-sized jump (teleport, refocus): snap
  if (!cam || cam.world !== frame.world || state.camMode === "instant" ||
      Math.hypot(tx - cam.x, ty - cam.y) > viewR * 3) {
    canvas._cam = { x: tx, y: ty, vx: 0, vy: 0, t: now,
                    world: frame.world, settled: true };
    return [tx, ty];
  }
  if (state.camMode === "lazy") {
    if (Math.hypot(tx - cam.x, ty - cam.y) > viewR) { cam.x = tx; cam.y = ty; }
    cam.t = now;
    cam.settled = true;
    return [cam.x, cam.y];
  }
  // "smoother": stiction — a resting camera ignores drift under CAM_STICTION,
  // then follows on a gentler spring until the target comes to rest again
  const soft = state.camMode === "smoother";
  if (soft && cam.stuck !== false &&
      Math.hypot(tx - cam.x, ty - cam.y) <= CAM_STICTION) {
    cam.t = now;
    cam.settled = true;
    return [cam.x, cam.y];
  }
  cam.stuck = false;
  const [spring, friction] = soft ? CAM_SOFT : [CAM_SPRING, CAM_FRICTION];
  const dt = Math.min(0.05, Math.max(0, (now - cam.t) / 1000));
  cam.t = now;
  cam.vx += ((tx - cam.x) * spring - cam.vx * friction) * dt;
  cam.vy += ((ty - cam.y) * spring - cam.vy * friction) * dt;
  cam.x += cam.vx * dt;
  cam.y += cam.vy * dt;
  cam.settled = Math.hypot(tx - cam.x, ty - cam.y) < 0.02 &&
                Math.hypot(cam.vx, cam.vy) < 0.05;
  if (cam.settled) { cam.x = tx; cam.y = ty; cam.vx = cam.vy = 0; cam.stuck = true; }
  return [cam.x, cam.y];
}

// Match the backing store to the displayed box so canvas pixels are screen pixels.
function fitCanvas(canvas) {
  const dpr = window.devicePixelRatio || 1;
  const w = Math.round(canvas.clientWidth * dpr), h = Math.round(canvas.clientHeight * dpr);
  if (w && h && (canvas.width !== w || canvas.height !== h)) {
    canvas.width = w;
    canvas.height = h;
  }
  return dpr;
}

// speech bubble above a tile, clamped to a readable width at any zoom
function drawBubble(ctx, cx, top, text, dpr) {
  const font = 11 * dpr, maxW = 130 * dpr;
  ctx.font = `${font}px ui-monospace, Menlo, Consolas, monospace`;
  let t = text;
  if (ctx.measureText(t).width > maxW) {
    while (t.length > 1 && ctx.measureText(t + "…").width > maxW) t = t.slice(0, -1);
    t += "…";
  }
  const w = ctx.measureText(t).width + 8 * dpr, h = font + 6 * dpr;
  const x = cx - w / 2, y = top - h - 4 * dpr;
  ctx.fillStyle = "#e8ecf4";
  ctx.beginPath();
  ctx.roundRect ? ctx.roundRect(x, y, w, h, 3 * dpr) : ctx.rect(x, y, w, h);
  ctx.fill();
  ctx.beginPath();
  ctx.moveTo(cx - 3 * dpr, y + h);
  ctx.lineTo(cx + 3 * dpr, y + h);
  ctx.lineTo(cx, y + h + 4 * dpr);
  ctx.fill();
  ctx.fillStyle = "#14161c";
  ctx.textAlign = "center";
  ctx.textBaseline = "middle";
  ctx.fillText(t, cx, y + h / 2 + dpr);
  ctx.textAlign = "start";
  ctx.textBaseline = "alphabetic";
}

function drawFrame(canvas, frame) {
  canvas._frame = frame;                           // so the zoom slider can redraw
  const dpr = fitCanvas(canvas);
  const ctx = canvas.getContext("2d");
  ctx.imageSmoothingEnabled = false;
  ctx.clearRect(0, 0, canvas.width, canvas.height);
  const tiles = frame.tiles || (frame.visible && frame.visible.tiles) || [];
  if (!tiles.length) return;

  const size = state.zoom * dpr;                   // pixels per tile, never fitted
  const drawnAt = performance.now();
  const [cx, cy] = cameraCenter(canvas, frame, tiles, size, drawnAt);
  if (!canvas._cam.settled) startAnimLoop();       // keep gliding between frames
  const px = (x) => Math.floor(canvas.width / 2 + (x - cx) * size - size / 2);
  const py = (y) => Math.floor(canvas.height / 2 - (y - cy) * size - size / 2);
  canvas._view = { cx, cy, size, dpr };             // so a click can find its tile

  for (const [x, y, kind, sprite, base] of tiles) {
    if (kind === "wall" || kind === "trap") ctx.fillStyle = "#171b23";
    else ctx.fillStyle = "#0f1218";
    ctx.fillRect(px(x), py(y), size, size);
    // ground under overlays; a lilypad stacks [grass, water] under the pad
    for (const layer of Array.isArray(base) ? base : [base])
      if (layer) drawSprite(ctx, layer, px(x), py(y), size);
    drawSprite(ctx, sprite || 0, px(x), py(y), size);
  }

  for (const surf of (frame.surfaces || (frame.visible && frame.visible.surfaces) || []))
    drawSprite(ctx, state.surfaceTiles[surf.kind] ?? 0,
               px(surf.pos[0]), py(surf.pos[1]), size);

  // drops are drawn desaturated so they look lifeless on the ground
  for (const item of (frame.items || (frame.visible && frame.visible.items) || [])) {
    const tiers = state.tierTiles[item.kind];
    const index = tiers && item.tier >= 0 ? tiers[item.tier]
      : state.tiles[item.kind] ?? state.tiles.bottle_empty ?? 0;
    drawSprite(ctx, index, px(item.pos[0]), py(item.pos[1]), size, "inert");
  }

  for (const pile of (frame.gold || (frame.visible && frame.visible.gold) || [])) {
    ctx.fillStyle = "#d9a441";
    ctx.beginPath();
    ctx.arc(px(pile.pos[0]) + size / 2, py(pile.pos[1]) + size / 2, size / 6, 0, 7);
    ctx.fill();
  }

  const now = performance.now();
  const anims = (canvas._anims || []).filter((a) => now < a.start + a.dur);
  const offsets = animOffsets(anims, now);

  const entities = frame.entities || (frame.visible && frame.visible.entities) || [];
  for (const ent of entities) {
    const off = offsets.get(ent.eid) || [0, 0];
    const x = px(ent.pos[0] + off[0]), y = py(ent.pos[1] + off[1]);
    if (ent.kind === "char" && state.showColors) {   // guild corner brackets
      const u = Math.max(1, size / 16);          // one sprite pixel, 3x3 L per corner
      ctx.fillStyle = guildColor(ent.guild_id) || "#9aa7bb";
      for (const [right, down] of [[0, 0], [1, 0], [0, 1], [1, 1]]) {
        const bx = x + right * (size - 3 * u), by = y + down * (size - 3 * u);
        ctx.fillRect(bx, by + down * 2 * u, 3 * u, u);   // horizontal arm
        ctx.fillRect(bx + right * 2 * u, by, u, 3 * u);  // vertical arm
      }
    }
    drawSprite(ctx, spriteFor(ent), x, y, size, ent.hit ? "hurt" : "base");
    if (ent.held && state.tiles[ent.held] !== undefined) {   // what they're holding
      const half = Math.max(6, Math.round(size * 0.6));
      drawSprite(ctx, state.tiles[ent.held], x + size - half, y + size - half, half);
    }
    if (ent.hp_frac !== undefined && ent.hp_frac < 1) {
      ctx.fillStyle = "#000a";
      ctx.fillRect(x, y - 3, size, 3);
      ctx.fillStyle = ent.faction === "guild" ? "#63c07a" : "#d1615d";
      ctx.fillRect(x, y - 3, size * ent.hp_frac, 3);
    }
  }

  drawAnims(ctx, anims, now, px, py, size);

  for (const ent of entities)                      // bubbles on top of everything
    if (ent.say) drawBubble(ctx, px(ent.pos[0]) + size / 2, py(ent.pos[1]), ent.say, dpr);

  if (frame.bounds) {                              // faint outline of the whole map
    const [w, h] = frame.bounds;
    ctx.strokeStyle = "#8fa3c880";
    ctx.lineWidth = 1;
    ctx.strokeRect(px(0) + 0.5, py(h - 1) + 0.5, w * size - 1, h * size - 1);
  }

  // your own characters get a marker so they are findable in a crowd
  for (const ch of frame.chars || []) {
    ctx.strokeStyle = "#d9a441";
    ctx.lineWidth = 1;
    ctx.strokeRect(px(ch.pos[0]) + 0.5, py(ch.pos[1]) + 0.5, size - 1, size - 1);
  }
}

// --- spectate ---------------------------------------------------------------

function openSpectate() {
  if (state.spectateSource) state.spectateSource.close();
  const params = new URLSearchParams();
  if (state.follow) params.set("guild", state.follow);
  if (state.followChar) params.set("char", state.followChar);
  if (state.map) params.set("map", state.map);
  if (state.center) { params.set("x", state.center[0]); params.set("y", state.center[1]); }
  const source = new EventSource("/events/spectate?" + params.toString());
  source.onmessage = (event) => {
    const frame = JSON.parse(event.data);
    ensureSprites(frame);
    queueAnims($("spectate-canvas"), frame);
    drawFrame($("spectate-canvas"), frame);
    setStatus("tick " + frame.tick);
    state.map = frame.world;
    $("spectate-caption").textContent = state.followChar
      ? `following ${state.followCharName || state.followChar} on ${frame.world}`
      : state.follow
        ? `following ${state.follow} on ${frame.world}`
        : `${frame.world} — free roam, view ${frame.view.join(", ")} (arrow keys)`;
  };
  state.spectateSource = source;
}

// slots arrive as a kind on the spectate roster and as an item in a frame
const kindOf = (slot) => (slot && typeof slot === "object" ? slot.kind : slot);

// a character's portrait: their outfit (or bare look), weapon in the corner
function paintPortrait(canvas, char, size, withGear = false) {
  const draw = () => {
    const ctx = canvas.getContext("2d");
    ctx.imageSmoothingEnabled = false;
    drawSprite(ctx, state.tiles[kindOf(char.equipment.outfit)]
      ?? state.looks[char.look] ?? state.bareTile, 0, 0, size);
    const hand = kindOf(char.equipment.hand);
    const half = Math.round(size * 0.625);
    if (withGear && state.tiles[hand] !== undefined)
      drawSprite(ctx, state.tiles[hand], size - half, size - half, half);
  };
  sheet.complete ? draw() : sheet.addEventListener("load", draw, { once: true });
}

// one line per character on the selected map: icon, name, level, equipment
function rosterRow(char) {
  const row = document.createElement("div");
  row.className = "roster-row" + (char.char_uid === state.followChar ? " followed" : "");
  row.onclick = () => {
    state.followChar = state.followChar === char.char_uid ? null : char.char_uid;
    state.followCharName = state.followChar ? char.name : null;
    state.follow = null;
    state.center = null;
    refreshGuilds();
    openSpectate();
  };
  const outfit = char.equipment.outfit;
  const kit = [outfit, char.equipment.hand]
    .filter(Boolean).map((k) => itemTag(k)).join("");
  row.innerHTML = `
    <canvas class="portrait" width="32" height="32"></canvas>
    <div class="roster-info">
      <div>${char.name} <small>lvl ${char.level}</small></div>
      <div>${kit || '<span class="tag">bare-handed</span>'}</div>
    </div>`;
  paintPortrait(row.querySelector("canvas.portrait"), char, 32, true);
  return row;
}

async function refreshGuilds() {
  const data = await (await fetch("/api/spectate/guilds")).json();
  ensureSprites(data);
  state.maps = data.maps || [];
  if (!state.map && state.maps.length) state.map = state.maps[0].id;

  const maps = $("map-list");
  maps.innerHTML = "";
  for (const map of data.maps || []) {
    const li = document.createElement("li");
    li.textContent = `${map.name} (${map.width}x${map.height})`;
    if (map.id === state.map) li.className = "followed";
    li.onclick = () => {
      state.map = map.id;
      state.follow = null;
      state.followChar = state.followCharName = null;
      state.center = null;
      refreshGuilds();
      openSpectate();
    };
    maps.appendChild(li);
  }

  const list = $("guild-list");
  list.innerHTML = "";
  for (const guild of data.guilds) {
    if (guild.color) state.guildColors[guild.guild_id] = guild.color;
    const li = document.createElement("li");
    const here = (guild.roster || []).filter((c) => c.world === state.map);
    const header = document.createElement("div");
    header.className = "guild-header" + (guild.guild_id === state.follow ? " followed" : "");
    const swatch = document.createElement("span");
    swatch.className = "swatch";
    swatch.style.background = guildColor(guild.guild_id);
    header.append(swatch, `${guild.name} — ${here.length} here / ${guild.characters} total`);
    header.onclick = () => {
      state.follow = state.follow === guild.guild_id ? null : guild.guild_id;
      state.followChar = state.followCharName = null;
      state.center = null;
      refreshGuilds();
      openSpectate();
    };
    li.appendChild(header);
    for (const char of here.sort((a, b) => b.level - a.level || a.name.localeCompare(b.name)))
      li.appendChild(rosterRow(char));
    list.appendChild(li);
  }
}

// player view: up/down step through the follow list, in the order it is shown
document.addEventListener("keydown", (event) => {
  const dir = { ArrowUp: -1, ArrowDown: 1 }[event.key];
  if (!dir || !$("tab-player").classList.contains("active")) return;
  event.preventDefault();
  const uids = [...$("player-roster").querySelectorAll(".roster-row")]
    .map((row) => row.dataset.uid);
  if (uids.length) setFocus(uids[(uids.indexOf(state.focus) + dir + uids.length) % uids.length]);
});

document.addEventListener("keydown", (event) => {
  const step = { ArrowUp: [0, 8], ArrowDown: [0, -8], ArrowLeft: [-8, 0], ArrowRight: [8, 0] }[event.key];
  if (!step || !$("tab-spectate").classList.contains("active")) return;
  event.preventDefault();
  state.follow = null;
  state.followChar = state.followCharName = null;
  state.center = state.center || [24, 12];
  state.center = [Math.max(0, state.center[0] + step[0]), Math.max(0, state.center[1] + step[1])];
  openSpectate();
});

// --- player / guild views ---------------------------------------------------

const LOGGED = new Set(["attack", "death", "pickup", "opened", "xp", "stat_up", "gold",
  "heal", "equip", "drop", "used", "status", "trap_fire", "boss_slain", "sale", "buy",
  "market_trade", "recruit", "embark", "returned", "band_refresh_warning", "band_refresh",
  "say", "summon", "blast", "nova",
  "brew_started", "brew_stirred", "brew_ruined", "brew_failed", "brewed", "tasted",
  "smelted", "forge_started", "forge_struck", "forged", "craft_spoiled",
  "learned", "warded", "gust", "blink", "surface", "overburdened",
  "charge", "ride", "pulled",
  "cast_bolt", "veiled", "field", "burst", "attuned", "unattuned", "miscast",
  "purged", "forgotten"]);

// monster labels are registry kinds ("slime_green"); names pass through untouched
const who = (name, fallback) => (name ?? fallback ?? "?").toString().replace(/_/g, " ");

function describe(event) {
  switch (event.kind) {
    case "brew_stirred": return `stirred the brew — ${event.tell.replace(/_/g, " ")}`;
    case "brew_failed": return `brew failed — ${event.why}`;
    case "brewed": return `brewed ${event.item} (tier ${event.tier})`;
    case "tasted": return `tasted ${event.item} — ${event.essence}`;
    case "smelted": return `smelted ${event.item}`;
    case "forge_started": return `began forging ${event.product}`;
    case "forge_struck": return `struck the forge — ${event.tell.replace(/_/g, " ")}`;
    case "forged": return `forged ${event.item} (tier ${event.tier})`;
    case "learned": return `learned ${event.spell}`;
    case "attuned": return `attuned to ${event.essence}`;
    case "unattuned": return `the ${event.essence} bond faded`;
    case "forgotten": return `forgot ${event.spell}`;
    case "miscast": return `miscast — the focus flared ${event.essence}`;
    case "cast_bolt": return `wove a ${event.essence} bolt` +
             (event.weave ? ` (${event.weave})` : "");
    case "veiled": return `veiled in ${event.essence}` +
             (event.weave ? ` (${event.weave})` : "");
    case "field": return `laid a ${event.essence} field` +
             (event.weave ? ` (${event.weave})` : "");
    case "burst": return `loosed a ${event.essence} ring` +
             (event.weave ? ` (${event.weave})` : "");
    case "purged": return "was purged of every working";
    case "surface": return `${event.surface} spreads at ${event.pos}`;
    case "attack":
      return `${who(event.attacker_name, event.attacker ?? "trap")} hit ` +
             `${who(event.target_name, event.target)} for ${event.dmg}` +
             (event.immune ? " (immune)" : "");
    case "death": return `${who(event.name, event.kind_name)} died at ${event.pos}`;
    case "pickup": return `picked up ${event.items.length} item(s)`;
    case "xp": return `+${event.amount} xp`;
    case "gold": return `+${event.amount} gold`;
    case "stat_up": return `${event.stat} raised to ${event.value}`;
    case "say": return `“${event.text}”`;
    case "charge": return `charged to ${event.to}`;
    case "ride": return `rode the rails to ${event.to}`;
    case "pulled": return "was reeled in";
    case "band_refresh_warning": return `band ${event.band} refreshes in ${event.in_ticks} ticks`;
    default: return event.kind.replace(/_/g, " ");
  }
}

function charCard(char, withPortrait = true) {
  const div = document.createElement("div");
  div.className = char.char_uid === state.focus ? "char focused" : "char";
  div.dataset.uid = char.char_uid;
  div.onclick = () => setFocus(char.char_uid);
  const hp = Math.round(100 * char.hp / char.max_hp);
  const stam = Math.round(100 * char.stamina / char.max_stamina);
  const mana = Math.round(100 * char.mana / char.max_mana);
  const statuses = (char.statuses || []).map((s) =>
    `<span class="tag status">${s.kind} ${s.ticks_left}</span>`).join("");
  // one tag per filled slot; `held` only when it isn't just the equipped weapon
  const gear = [
    char.equipment.outfit ? itemTag(char.equipment.outfit) : "",
    ...["hand", "offhand", "trinket", "boots"].map((slot) => char.equipment[slot])
      .filter(Boolean).map((i) => itemTag(i.kind, i.kind, i)),
    char.held && char.held !== (char.equipment.hand || {}).kind
      ? itemTag(char.held, `holding ${char.held}`) : "",
  ].join("") || "—";
  const bag = countTags(char.inventory || []);
  const gifts = char.gifts || [];                  // gifted stats get a star
  const spells = (char.spells || []).length
    ? `<div>spells <small>${char.spells.length}/${char.spell_cap}</small>
       ${char.spells.map((s) => `<span class="tag tome">${s}</span>`).join("")}</div>` : "";
  const craft = !char.craft ? "" : char.craft.kind === "brew"
    ? `<div><span class="tag status">brewing — stirred ${char.craft.stir}x</span></div>`
    : `<div><span class="tag status">forging ${char.craft.product} — ${char.craft.strikes} strikes</span></div>`;
  div.innerHTML = `
    <h3>${withPortrait ? '<canvas class="portrait" width="16" height="16"></canvas>' : ""}
        ${char.name} <small>${char.pos ? char.pos.join(",") : "village"}</small></h3>
    <div class="bar hp"><span style="width:${hp}%"></span></div>
    <div class="bar stam"><span style="width:${stam}%"></span></div>
    <div class="bar mana"><span style="width:${mana}%"></span></div>
    <div class="stats">
      ${Object.entries(char.stats).map(([k, v]) =>
        `<div>${k}${gifts.includes(k) ? "★" : ""} <b>${v}</b></div>`).join("")}
      <div>lvl <b>${char.level}</b></div>
      <div>xp <b>${char.xp}</b></div><div>armor <b>${char.armor}</b></div>
      <div>vision <b>${char.vision}</b></div>
      <div>carry <b>${char.carry.used}/${char.carry.cap}</b> bulk</div>
    </div>
    ${spells}${craft}
    <div>${statuses}</div>
    <h4>equipped</h4>
    <div class="stacked">${gear}</div>
    <h4>carrying</h4>
    <div class="stacked">${bag}</div>`;
  const portrait = div.querySelector("canvas.portrait");
  if (portrait) paintPortrait(portrait, char, 16);
  return div;
}

// the player view follows one character; clicking anywhere they appear switches
function setFocus(uid) {
  state.focus = uid;
  for (const card of document.querySelectorAll(".char"))
    card.classList.toggle("focused", card.dataset.uid === state.focus);
  const canvas = $("player-canvas");
  if (canvas._frame) drawFrame(canvas, canvas._frame);
  renderFollowed();
}

function hasFocus(frame) {
  return !state.focus || (frame.chars || []).some((c) => c.char_uid === state.focus);
}

function blankMap(caption) {
  const canvas = $("player-canvas");
  canvas._frame = null;
  const ctx = canvas.getContext("2d");
  ctx.clearRect(0, 0, canvas.width, canvas.height);
  $("player-caption").textContent = caption;
}

// Frames arrive per world, so remember every character we have been shown and
// drop the ones missing from their own world's frame (dead, or moved on).
// The followed character survives the gap: walking home to the village means
// leaving the map frame a moment before turning up in the village one.
function trackChars(frame) {
  for (const char of frame.chars || []) {
    char.seen_tick = frame.tick;
    state.chars.set(char.char_uid, char);
  }
  const here = new Set((frame.chars || []).map((c) => c.char_uid));
  for (const [uid, char] of state.chars)
    if (char.world === frame.world && !here.has(uid) && uid !== state.focus)
      state.chars.delete(uid);
  const followed = state.chars.get(state.focus);
  if (!followed || frame.tick - followed.seen_tick > FOCUS_GRACE) {
    state.chars.delete(state.focus);            // gone for good, not just moving
    state.focus = state.chars.keys().next().value ?? null;
  }
}

// one follow target: portrait, name, health, and where they stand
function followRow(char) {
  const row = document.createElement("div");
  row.className = "roster-row" + (char.char_uid === state.focus ? " followed" : "");
  row.dataset.uid = char.char_uid;
  row.onclick = () => setFocus(char.char_uid);
  const hp = Math.round(100 * char.hp / char.max_hp);
  row.innerHTML = `
    <canvas class="portrait" width="32" height="32"></canvas>
    <div class="roster-info grow">
      <div>${char.name} <small>${char.pos ? char.pos.join(",") : ""}</small></div>
      <div class="bar hp"><span style="width:${hp}%"></span></div>
      <small>${char.hp}/${char.max_hp} hp · lvl ${char.level}</small>
    </div>`;
  paintPortrait(row.querySelector("canvas.portrait"), char, 32, true);
  return row;
}

// the follow list: every character the guild has, under the map they are on
function renderRoster() {
  const groups = new Map([...state.maps.map((m) => m.id), "village"].map((w) => [w, []]));
  for (const char of state.chars.values()) {
    if (!groups.has(char.world)) groups.set(char.world, []);
    groups.get(char.world).push(char);
  }
  const list = $("player-roster");
  const signature = [...groups].map(([world, chars]) => `${world}:${chars.map(
    (c) => `${c.char_uid},${c.hp},${c.pos}`).join(";")}`).join("|") + `::${state.focus}`;
  if (list._signature === signature) return;
  list._signature = signature;
  const nodes = [];
  for (const [world, chars] of groups) {
    if (!chars.length) continue;
    const head = document.createElement("div");
    head.className = "roster-group";
    head.textContent = `${world} · ${chars.length}`;
    chars.sort((a, b) => a.name.localeCompare(b.name));
    nodes.push(head, ...chars.map(followRow));
  }
  if (!nodes.length) {
    const empty = document.createElement("p");
    empty.className = "hint";
    empty.textContent = "No characters yet — recruit one with a bot.";
    nodes.push(empty);
  }
  list.replaceChildren(...nodes);
}

// One atomic swap per tick: clearing first is what made the card flash.
function renderFollowed() {
  const char = state.chars.get(state.focus);
  renderRoster();
  $("player-chars").replaceChildren(...(char ? [charCard(char)] : []));
  const lines = char ? state.log.filter((entry) => entry.eids.includes(char.eid)) : [];
  $("player-log").replaceChildren(...lines.map((entry) => {
    const li = document.createElement("li");
    li.innerHTML = `<b>${entry.tick}</b> ${entry.text}`;
    return li;
  }));
}

// who a log line belongs to: the actor, and for a fight both sides of it
function eventActors(event) {
  return [event.eid, event.attacker, event.target].filter((eid) => eid != null);
}

function renderPlayer(frame) {
  if (frame.world !== "village") {
    if (hasFocus(frame)) {
      state.lastMap = frame;
      queueAnims($("player-canvas"), frame);
      drawFrame($("player-canvas"), frame);
      const following = state.chars.get(state.focus);
      $("player-caption").textContent =
        `${frame.world} — tick ${frame.tick}` +
        (following ? ` — following ${following.name}` : "") +
        (frame.next_refresh ? ` — band ${frame.next_refresh.band} refreshes in ${frame.next_refresh.in_ticks}` : "");
    }
  } else {
    state.village = frame;
    if (frame.guild.color) state.guildColors[frame.guild.guild_id] = frame.guild.color;
  }
  trackChars(frame);
  // in the village there is no map to draw: blank it rather than leaving the
  // last dungeon view up, and the next map frame brings the view straight back
  const followed = state.chars.get(state.focus);
  if (followed && followed.world === "village") blankMap(`${followed.name} is in the village`);

  for (const event of frame.events || []) {
    if (!LOGGED.has(event.kind)) continue;
    state.log.unshift({eids: eventActors(event), tick: frame.tick, text: describe(event)});
  }
  state.log = state.log.slice(0, 400);
  renderFollowed();
  renderGuild();
}

// where the guild's characters can be: everywhere, the village, every map
function renderGuildFilter() {
  const worlds = ["all", "village", ...state.maps.map((m) => m.id)];
  for (const char of state.chars.values())
    if (!worlds.includes(char.world)) worlds.push(char.world);
  const counts = new Map();
  for (const char of state.chars.values())
    counts.set(char.world, (counts.get(char.world) || 0) + 1);
  const bar = $("guild-filter");
  const signature = worlds.join("|") + "::" + [...counts] + "::" + state.guildFilter;
  if (bar._signature === signature) return;
  bar._signature = signature;
  bar.replaceChildren(...worlds.map((world) => {
    const button = document.createElement("button");
    const n = world === "all" ? state.chars.size : counts.get(world) || 0;
    button.textContent = `${world === "all" ? "everywhere" : world} (${n})`;
    button.classList.toggle("active", state.guildFilter === world);
    button.onclick = () => { state.guildFilter = world; renderGuild(); };
    return button;
  }));
}

// the character's recent log lines, for under their card in the guild view
function charLog(char, limit = 10) {
  const ul = document.createElement("ul");
  ul.className = "char-log";
  for (const entry of state.log.filter((e) => e.eids.includes(char.eid)).slice(0, limit)) {
    const li = document.createElement("li");
    li.innerHTML = `<b>${entry.tick}</b> ${entry.text}`;
    ul.appendChild(li);
  }
  return ul;
}

function renderGuild() {
  const village = state.village;
  if (!village) return;
  renderGuildFilter();
  const columns = [];
  for (const char of state.chars.values()) {
    if (state.guildFilter !== "all" && char.world !== state.guildFilter) continue;
    const panel = document.createElement("div");
    panel.className = "panel";
    panel.appendChild(charCard(char));
    panel.appendChild(charLog(char));
    columns.push(panel);
  }
  const guild = village.guild;
  const panel = document.createElement("div");
  panel.className = "panel";
  panel.innerHTML = `
    <h2>${guild.name}</h2>
    <table>
      <tr><td>gold</td><td class="v">${guild.gold}</td></tr>
      <tr><td>in village</td><td class="v">${guild.chars_here.length}</td></tr>
      ${Object.entries(guild.chars_by_world).map(([w, uids]) =>
        `<tr><td>${w}</td><td class="v">${uids.length}</td></tr>`).join("")}
    </table>
    <h2>Guild inventory</h2>
    <div class="stacked">${countTags(guild.inventory)}</div>
    <h2>Market</h2>
    <div class="stacked">${guild.market_listings.map((l) =>
      itemTag(l.kind, `${l.kind} ${l.price}g${l.mine ? " (yours)" : ""}`)).join("") || "—"}</div>`;
  columns.unshift(panel);
  $("guild-columns").replaceChildren(...columns);
}

async function openPlayerViews() {
  const response = await fetch("/api/me");
  const unlocked = response.ok;
  $("player-locked").classList.toggle("hidden", unlocked);
  $("guild-locked").classList.toggle("hidden", unlocked);
  $("guild-tools").classList.toggle("hidden", !unlocked);
  if (!unlocked) return;
  state.village = await response.json();
  const me = state.village.guild;
  if (me.color) state.guildColors[me.guild_id] = me.color;
  const picker = $("guild-color");
  picker.value = guildColor(me.guild_id);
  picker.onchange = async () => {
    await fetch("/api/guild/color", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ color: picker.value }) });
    state.guildColors[me.guild_id] = picker.value;
    refreshGuilds();
  };
  renderGuild();
  state.meSource = new EventSource("/events/me");
  state.meSource.onmessage = (event) => {
    const frame = JSON.parse(event.data);
    ensureSprites(frame);
    renderPlayer(frame);
  };
}

// --- boot -------------------------------------------------------------------

function setZoom(value) {
  state.zoom = value;
  for (const slider of document.querySelectorAll("input.zoom")) slider.value = value;
  for (const label of document.querySelectorAll(".zoom-value")) label.textContent = value;
  for (const canvas of document.querySelectorAll("canvas.map"))
    if (canvas._frame) drawFrame(canvas, canvas._frame);
}

for (const slider of document.querySelectorAll("input.zoom"))
  slider.oninput = () => setZoom(Number(slider.value));
for (const box of document.querySelectorAll("input.colors"))
  box.onchange = () => {
    state.showColors = box.checked;
    for (const other of document.querySelectorAll("input.colors"))
      other.checked = box.checked;
    for (const canvas of document.querySelectorAll("canvas.map"))
      if (canvas._frame) drawFrame(canvas, canvas._frame);
  };
for (const sel of document.querySelectorAll("select.camera"))
  sel.onchange = () => {
    state.camMode = sel.value;
    for (const other of document.querySelectorAll("select.camera"))
      other.value = sel.value;
  };
setZoom(state.zoom);
window.addEventListener("resize", () => setZoom(state.zoom));

// the hash is the tab, so a refresh or a bookmark lands where you left off
function showTab(name) {
  if (!$("tab-" + name)) name = "spectate";
  for (const button of document.querySelectorAll("#tabs button"))
    button.classList.toggle("active", button.dataset.tab === name);
  for (const tab of document.querySelectorAll(".tab"))
    tab.classList.toggle("active", tab.id === "tab-" + name);
  setZoom(state.zoom);                             // canvases size only once visible
}

// clicking one of your own characters on the map follows them
$("player-canvas").onclick = (event) => {
  const canvas = $("player-canvas");
  if (!canvas._view || !canvas._frame) return;
  const { cx, cy, size, dpr } = canvas._view;
  const rect = canvas.getBoundingClientRect();
  const x = Math.round(cx + ((event.clientX - rect.left) * dpr - canvas.width / 2) / size);
  const y = Math.round(cy - ((event.clientY - rect.top) * dpr - canvas.height / 2) / size);
  const hit = (canvas._frame.chars || [])
    .find((c) => c.pos && c.pos[0] === x && c.pos[1] === y);
  if (hit) setFocus(hit.char_uid);
};

for (const button of document.querySelectorAll("#tabs button"))
  button.onclick = () => { location.hash = button.dataset.tab; };
window.addEventListener("hashchange", () => showTab(location.hash.slice(1)));
showTab(location.hash.slice(1));

(async function boot() {
  const data = await (await fetch("/api/tiles")).json();
  COLS = data.columns;
  COUNT = data.count;
  state.tiles = data.tiles;
  state.fxTiles = data.fx_tiles || {};
  state.types = data.types;
  state.tierTiles = data.tier_tiles;
  state.surfaceTiles = data.surface_tiles;
  state.bareTile = data.bare_tile;
  state.looks = data.looks;
  openSpectate();
  refreshGuilds();
  setInterval(refreshGuilds, 5000);
  openPlayerViews();
})();
