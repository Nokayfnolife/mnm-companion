// "Ask the guide": answers a signed-in player's question from the site's wiki copy using Claude.
// Secrets (Supabase > Edge Functions > Secrets):
//   ANTHROPIC_API_KEY  required
//   ASK_DAILY_LIMIT    optional, questions per player per day (default 25)
//   ASK_MODEL          optional (default claude-haiku-5-5)
//   SITE_URL           optional, where wiki.json lives (default https://mnmcompanion.gg)
// Needs supabase/ask.sql (the ask_usage table and ask_bump function) run once.

const SITE = Deno.env.get("SITE_URL") ?? "https://mnmcompanion.gg";
const MODEL = Deno.env.get("ASK_MODEL") ?? "claude-haiku-5-5";
const LIMIT = Number(Deno.env.get("ASK_DAILY_LIMIT") ?? "25");
const SB_URL = Deno.env.get("SUPABASE_URL") ?? "";

const CORS = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Headers": "authorization, x-client-info, apikey, content-type",
  "Access-Control-Allow-Methods": "POST, OPTIONS",
};
const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), { status, headers: { ...CORS, "Content-Type": "application/json" } });

function serviceKey(): string {
  const k = Deno.env.get("SUPABASE_SERVICE_ROLE_KEY");
  if (k) return k;
  try {
    const all = JSON.parse(Deno.env.get("SUPABASE_SECRET_KEYS") ?? "{}");
    return (Object.values(all)[0] as string) ?? "";
  } catch { return ""; }
}
function svcHeaders(key: string): Record<string, string> {
  const h: Record<string, string> = { apikey: key, "Content-Type": "application/json" };
  if (key.startsWith("eyJ")) h.Authorization = `Bearer ${key}`; // legacy JWT-style service_role key
  return h;
}

const norm = (s: unknown) => String(s ?? "").toLowerCase().replace(/[’']/g, "'").replace(/[^a-z0-9' ]+/g, " ").replace(/\s+/g, " ").trim();
const trim = (s: unknown, n: number) => { const t = String(s ?? "").replace(/\s+/g, " ").trim(); return t.length > n ? t.slice(0, n - 1) + "…" : t; };

type Doc = { t: string; x: string; w: string };
let CACHE: { docs: Doc[]; at: number } | null = null;

// deno-lint-ignore no-explicit-any
async function corpus(): Promise<Doc[]> {
  if (CACHE && Date.now() - CACHE.at < 3_600_000) return CACHE.docs;
  const [w, c] = await Promise.all([
    fetch(`${SITE}/data/wiki.json`).then((r) => r.json()),
    fetch(`${SITE}/curated.json`).then((r) => r.json()),
  ]);
  const docs: Doc[] = [];
  const add = (t: string, x: string) => { if (t) docs.push({ t, x: trim(x, 700), w: " " + norm(t + " " + x) + " " }); };
  // deno-lint-ignore no-explicit-any
  for (const it of Object.values<any>(w.items ?? {})) {
    const d = it.detail ?? {};
    const stats = Object.entries(d.stats ?? {}).map(([k, v]) => `${k} ${v}`).join(", ");
    const weapon = d.weapon ? Object.entries(d.weapon).map(([k, v]) => `${k} ${v}`).join(", ") : "";
    add(it.name, `Item. ${d.sub ?? it.type ?? ""}. Class: ${d.class ?? it.classes ?? "All"}. Race: ${d.race ?? it.races ?? "All"}.`
      + (stats ? ` Stats: ${stats}.` : "") + (weapon ? ` Weapon: ${weapon}.` : "") + (d.effect ? ` ${d.effect}.` : "")
      + ((d.tags ?? []).length ? ` ${d.tags.join(", ")}.` : "") + ` ${trim(d.drop ?? it.excerpt ?? "", 240)}`);
  }
  // deno-lint-ignore no-explicit-any
  for (const q of (w.quests ?? []) as any[]) {
    add(q.name, `Quest, level ${q.level ?? "?"}, in ${q.zone}. Classes: ${q.classes}.${q.reward ? ` Reward: ${q.reward}.` : ""} ${trim(q.excerpt, 300)}`);
  }
  // deno-lint-ignore no-explicit-any
  for (const z of Object.values<any>(w.zones ?? {})) {
    add(z.name, `Zone (${z.kind ?? "zone"})${z.levels ? `, levels ${z.levels[0]} to ${z.levels[1]}` : ""}.`);
    for (const cp of z.camps ?? []) {
      add(`${cp.area} (${cp.zone})`, `Hunting spot, ${cp.level?.text ?? ""}${cp.level?.group ? " (group)" : ""}. Mobs: ${cp.mobs ?? ""}.`
        + ((cp.named ?? []).length ? ` Named: ${cp.named.join(", ")}.` : "") + ((cp.loot ?? []).length ? ` Loot: ${cp.loot.join(", ")}.` : "") + ` ${cp.note ?? ""}`);
    }
  }
  // deno-lint-ignore no-explicit-any
  for (const g of Object.values<any>(w.guides ?? {})) {
    // deno-lint-ignore no-explicit-any
    for (const x of (g.gear ?? []) as any[]) add(x.name, `Class guide gear pick (${x.tier ?? ""}), ${x.slot}: ${x.stats}. From ${x.where}.`);
  }
  // deno-lint-ignore no-explicit-any
  for (const p of (c.plays ?? []) as any[]) {
    add(p.title, `Plan tip (${p.kind}${p.lvl ? `, levels ${p.lvl[0]} to ${p.lvl[1]}` : ""}${p.cities ? `, ${p.cities.join("/")}` : ""}${p.classes ? `, ${p.classes.join("/")}` : ""}). ${p.why ?? ""} ${(p.steps ?? []).join(" ")}`);
  }
  // deno-lint-ignore no-explicit-any
  for (const s of (c.sets ?? []) as any[]) {
    // deno-lint-ignore no-explicit-any
    const pieces = (s.pieces ?? []).map((x: any) => `${x.item} (${Object.entries(x.need ?? {}).map(([m, n]) => `${n}x ${m}`).join(", ")})`).join("; ");
    add(s.name, `Armor set. Turn in to ${s.giver ?? ""}. Materials from ${s.mob ?? ""}. Pieces: ${pieces}. ${s.tip ?? ""}`);
  }
  // deno-lint-ignore no-explicit-any
  for (const ci of (c.cities ?? []) as any[]) add(`${ci.name} (starting city)`, `${ci.region ?? ""}. ${ci.who ?? ""} Nearby zones: ${(ci.zones ?? []).join(", ")}.`);
  for (const [cls, list] of Object.entries(c.spells ?? {})) {
    if (Array.isArray(list)) add(`${cls} spells by level`, (list as [number, string][]).map(([lv, t]) => `${lv}: ${t}`).join("; "));
  }
  CACHE = { docs, at: Date.now() };
  return docs;
}

const STOP = new Set("a an the of to in on at for and or is are be do does did i im my me we you your it its what where how who which when why can could should would with from get got there any best good level lvl near find into have has this that".split(" "));

function retrieve(docs: Doc[], q: string, cls: string): string {
  const toks = [...new Set(norm(q).split(" ").filter((t) => t.length > 1 && !STOP.has(t)))];
  const stems = toks.map((t) => t.replace(/(ies|es|s)$/, "")).filter((t) => t.length > 1);
  const scored: [number, Doc][] = [];
  for (const d of docs) {
    let s = 0;
    const tl = " " + norm(d.t) + " ";
    for (const t of stems) {
      if (tl.includes(" " + t)) s += 3;
      if (d.w.includes(" " + t)) s += 1;
    }
    if (s > 0) {
      if (cls && d.w.includes(" " + norm(cls) + " ")) s += 0.5;
      scored.push([s, d]);
    }
  }
  scored.sort((a, b) => b[0] - a[0]);
  let out = "", n = 0;
  for (const [, d] of scored) {
    const line = `- ${d.t}: ${d.x}\n`;
    if (out.length + line.length > 9000 || n >= 40) break;
    out += line; n++;
  }
  return out;
}

const SYSTEM = `You are the guide inside MnM Companion, a fan-made planner for the MMORPG Monsters & Memories, which is in Early Access. Answer the player's question using only the wiki notes provided.
- Be brief and practical: two to six sentences, or a short list when naming several places or items.
- Write the exact name of any item, quest, zone or hunting spot from the notes in double square brackets, like [[Scarab Helm]], so the site can link it. Use the name exactly as it appears before the colon in the notes.
- Fit the answer to the player's class, race, level and starting city when the notes allow it.
- If the notes don't cover the question, say you couldn't find it in the wiki copy and suggest what to search for instead. Never invent stats, levels, drop sources or locations.`;

Deno.serve(async (req) => {
  if (req.method === "OPTIONS") return new Response("ok", { headers: CORS });
  if (req.method !== "POST") return json({ error: "Use POST." }, 405);

  const apiKey = Deno.env.get("ANTHROPIC_API_KEY");
  if (!apiKey) return json({ error: "The guide isn't switched on yet. Check back soon." }, 503);
  const svc = serviceKey();
  if (!SB_URL || !svc) return json({ error: "The guide is missing its server settings." }, 500);

  // who is asking
  const jwt = (req.headers.get("Authorization") ?? "").replace(/^Bearer\s+/i, "");
  const ur = await fetch(`${SB_URL}/auth/v1/user`, { headers: { apikey: svc, Authorization: `Bearer ${jwt}` } });
  if (!ur.ok) return json({ error: "Sign in to ask the guide." }, 401);
  const user = await ur.json();

  // deno-lint-ignore no-explicit-any
  let body: any;
  try { body = await req.json(); } catch { return json({ error: "Send a question." }, 400); }
  const q = String(body?.q ?? "").trim().slice(0, 300);
  if (q.length < 4) return json({ error: "Ask a full question." }, 400);
  const c = body?.char && typeof body.char === "object" ? body.char : null;
  const ch = c ? {
    cls: String(c.cls ?? "").slice(0, 30), race: String(c.race ?? "").slice(0, 30),
    level: Math.max(1, Math.min(60, Number(c.level) || 1)), city: String(c.city ?? "").slice(0, 40), solo: c.solo !== false,
  } : null;

  // daily limit per player
  const rr = await fetch(`${SB_URL}/rest/v1/rpc/ask_bump`, { method: "POST", headers: svcHeaders(svc), body: JSON.stringify({ uid: user.id, lim: LIMIT }) });
  if (!rr.ok) { console.error("ask_bump", rr.status, await rr.text()); return json({ error: "The guide couldn't check today's question limit. Try again later." }, 500); }
  const used = Number(await rr.json());
  if (used < 0) return json({ error: `You've asked ${LIMIT} questions today, the daily limit. It resets at midnight UTC.` }, 429);

  let ctx = "";
  try { ctx = retrieve(await corpus(), q, ch?.cls ?? ""); }
  catch (e) { console.error("corpus", e); return json({ error: "The guide couldn't read the wiki copy. Try again in a minute." }, 502); }

  const prompt = (ch ? `Player: level ${ch.level} ${ch.race} ${ch.cls}, started in ${ch.city}, plays ${ch.solo ? "solo" : "in a group"}.\n\n` : "")
    + `Wiki notes:\n${ctx || "(nothing in the wiki copy matched this question)"}\n\nQuestion: ${q}`;
  const ar = await fetch("https://api.anthropic.com/v1/messages", {
    method: "POST",
    headers: { "x-api-key": apiKey, "anthropic-version": "2023-06-01", "content-type": "application/json" },
    body: JSON.stringify({ model: MODEL, max_tokens: 700, system: SYSTEM, messages: [{ role: "user", content: prompt }] }),
  });
  if (!ar.ok) { console.error("anthropic", ar.status, await ar.text()); return json({ error: "The guide couldn't answer just now. Try again in a minute." }, 502); }
  const out = await ar.json();
  // deno-lint-ignore no-explicit-any
  const answer = ((out.content ?? []) as any[]).filter((b) => b.type === "text").map((b) => b.text).join("\n").trim();
  return json({ answer, left: Math.max(0, LIMIT - used) });
});
