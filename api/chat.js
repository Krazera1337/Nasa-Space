// Flame in Freefall: hazard assistant backend (Vercel serverless function).
// Written with AI assistance (Anthropic Claude).
//
// Talks to any OpenAI-compatible chat API (Groq, Gemini, OpenRouter, ...).
// Set these in Vercel -> Project -> Settings -> Environment Variables:
//   LLM_API_KEY   your provider key (never put it in index.html)
//   LLM_BASE_URL  default https://api.groq.com/openai/v1
//   LLM_MODEL     default llama-3.3-70b-versatile

const BASE = process.env.LLM_BASE_URL || "https://api.groq.com/openai/v1";
const MODEL = process.env.LLM_MODEL || "llama-3.3-70b-versatile";
const KEY = process.env.LLM_API_KEY;

// Best-effort rate limit so a public demo link can't drain the free quota.
// (Serverless instances don't share memory, so this is per instance.)
const hits = new Map();
const LIMIT = 20, WINDOW_MS = 10 * 60 * 1000;
function limited(ip) {
  const now = Date.now();
  const arr = (hits.get(ip) || []).filter((t) => now - t < WINDOW_MS);
  arr.push(now);
  hits.set(ip, arr);
  return arr.length > LIMIT;
}

const FINDINGS = `
SOURCE: NASA BASS-II (Burning and Suppression of Solids II), ISS Microgravity Science Glovebox.
Dataset: NASA PSI study PSI-25, DOI 10.60555/4qc4-de67. 129 burn tests by six research teams.
Report: BASS-II Summary Report, NASA/TM-20210011385 (2021). Page numbers below are printed pages.

SCOPE: all tests in microgravity, about 1 atm, 13.6-22.2% O2, airflow 0-~40 cm/s.
NO data for Moon/Mars partial gravity, reduced pressure, or O2 above 22.2%.

FINDINGS:
1. Thin PMMA (acrylic) sheets, opposed flow: flame goes out below ~1.5 cm/s airflow at 21% O2,
   rising to ~3.5 cm/s at ~16% O2. This extinction velocity does not depend on fuel thickness. [p. 25]
2. Black PMMA rods: flame spread seen down to 17.5% O2 in microgravity vs not below 19% in normal
   gravity, likely due to lower opposed-flow velocity in microgravity. [p. 50]
3. Clear PMMA rods: minimum O2 of 13.5% in microgravity vs 15.4% for upward spread on Earth (with
   4 cm/s forced flow). Material stays flammable under weak ventilation only found in microgravity, a
   "Goldilocks" flow typical of spacecraft ventilation near surfaces. Earth tests need a way to account
   for this. [p. 76]
4. NASA screens materials with the upward-burning NASA-STD-6001 Test 1, assumed worst case on Earth;
   BASS-II tests whether it is conservative in space. [p. 3]
5. Nomex III fabric (ISS fire barrier): all 3 samples failed to ignite (21-22.2% O2). [p. 46]
6. Wax candle ejected a burning molten droplet upstream: a spread hazard for melting plastics. [p. 46]
7. SIBAL cotton-fiberglass fabric, concurrent flow: quenching between 1 and 5 cm/s, higher in lower O2
   (tested 16-21% O2, up to 40 cm/s). First clean measurement of this low-speed quench boundary. [p. 93]
8. Lower O2 produced more CO per CO2 for concurrent-flow rods (less complete combustion). [p. 9]
9. Ranking by lowest O2 at which each material burned in the test table: clear PMMA rod 14.2%,
   thin PMMA film 15.0%, black PMMA rod 15.4%, SIBAL fabric 16.4%, PMMA sphere 17.2%,
   wax candle 17.4%, PMMA slab 17.9%, Nomex III never ignited.
`;

const MATERIALS = `material codes: film = thin PMMA/acrylic sheet (<1 mm, plastic film, thin plastic);
slab = thick PMMA 1-5 mm (panel, plate, block); rod_clear = clear PMMA rod; rod_black = black PMMA rod;
sibal = cotton-fiberglass fabric (cotton, cloth, clothing, bag, towel); nomex = Nomex III fabric;
sphere = PMMA spherical section; wax = wax candle.`;

const CHAT_PROMPT = `You are the hazard assistant on "Flame in Freefall", a student dashboard about fire safety in spacecraft.
Answer ONLY from the findings below. Never invent numbers, materials, or page references.
If the data does not cover something, say so plainly and say what new testing would be needed.

When the user describes a fire scenario or asks whether something would ignite or keep burning,
reply with ONE line and nothing else, in this exact form:
[[ASSESS {"f":"<material code>","o2":<number>,"u":<number>}]]
- Map the material to the closest code. ${MATERIALS}
- o2 is % by volume. If not given, use the current simulator value.
- u is airflow in cm/s. "fans off", "no ventilation", "still air" -> 0.5. "fans on/running", "ventilated" -> 10.
  If not given, use the current simulator value.
- If the material cannot reasonably be mapped to any code, ask one short question instead.

Otherwise answer in 2-5 short sentences of plain English for a non-expert, then cite pages like [p. 25].
Use **bold** sparingly. No headings, no lists longer than 3 items.

${FINDINGS}`;

const EXPLAIN_PROMPT = `You explain a hazard assessment from the "Flame in Freefall" dashboard to a non-expert.
The rating was computed by a fixed model over real ISS test data; do NOT change or second-guess the rating.
Write 2-4 short sentences: what the rating means, the main reason (airflow vs quench limit, oxygen, or
nearby tests), and one practical takeaway for spacecraft fire safety. Use only facts in the result and
the findings. Cite pages like [p. 25] where the result lists a citation. If the condition is outside the
tested range, say clearly that the data cannot rate it.

${FINDINGS}`;

async function llm(messages) {
  const r = await fetch(`${BASE}/chat/completions`, {
    method: "POST",
    headers: { "Content-Type": "application/json", Authorization: `Bearer ${KEY}` },
    body: JSON.stringify({ model: MODEL, messages, temperature: 0.2, max_tokens: 400 }),
  });
  if (!r.ok) throw new Error(`LLM ${r.status}: ${(await r.text()).slice(0, 200)}`);
  const j = await r.json();
  return j.choices?.[0]?.message?.content?.trim() || "";
}

const clip = (s, n) => String(s ?? "").slice(0, n);

export default async function handler(req, res) {
  if (req.method !== "POST") return res.status(405).json({ error: "POST only" });
  if (!KEY) return res.status(503).json({ error: "LLM_API_KEY not set" });

  const body = typeof req.body === "string" ? JSON.parse(req.body || "{}") : req.body || {};
  if (body.mode === "ping") return res.status(200).json({ ok: true });

  const ip = (req.headers["x-forwarded-for"] || "").split(",")[0] || "anon";
  if (limited(ip)) return res.status(429).json({ error: "Too many questions, try again in a few minutes." });

  try {
    let messages;
    if (body.mode === "explain") {
      messages = [
        { role: "system", content: EXPLAIN_PROMPT },
        { role: "user", content: `User asked: ${clip(body.question, 500)}\n\nAssessment result (JSON):\n${clip(JSON.stringify(body.result), 3000)}` },
      ];
    } else {
      const sim = body.sim || {};
      const history = (Array.isArray(body.messages) ? body.messages : [])
        .slice(-8)
        .filter((m) => m && (m.role === "user" || m.role === "assistant"))
        .map((m) => ({ role: m.role, content: clip(m.content, 800) }));
      if (!history.length) return res.status(400).json({ error: "No question" });
      messages = [
        { role: "system", content: `${CHAT_PROMPT}\nCurrent simulator: material=${clip(sim.material, 20)}, o2=${Number(sim.o2) || 21}, airflow=${Number(sim.airflow) || 3} cm/s.` },
        ...history,
      ];
    }
    const reply = await llm(messages);
    return res.status(200).json({ reply });
  } catch (e) {
    console.error(e);
    return res.status(502).json({ error: "Assistant unavailable" });
  }
}
