// Landing page (docs/UI_SPEC.md A7.2): the first screen, then six pitch sections to scroll (the gap at SF State, how
// it works, why the AI is essential, responsible by design, six programs, try it), English and Spanish. The demo phone number comes from
// GET /api/public/info and shows only when it is set; then the call button comes first and is the filled one. The view
// is a pure function (tested with node); the page part runs only in a browser.

import { fill } from "./shared/i18n.js";
import { telHref } from "./shared/format.js";

export const LANDING_STRINGS = {
  en: {
    title: "GatorPlate",
    headline_phone: "Check the money you may be missing — by phone or in your browser.",
    headline_web: "Check the money you may be missing — in your browser.",
    sub: "SF State students: CalFresh pays one person up to $306 a month for groceries, and it can open more help. A few minutes. Free. Estimates only — each agency decides.",
    talk: "Talk in your browser",
    call: "Call {number}",
    phone_note: "",
    about: "How it works and responsible AI",
    console: "For coordinators",
    "trust.label": "Privacy and limits",
    "trust.recorded": "Audio isn't recorded",
    "trust.ssn": "Never asks for your Social Security number or immigration status",
    "trust.estimate": "Estimates only — each agency decides",
    "more.label": "More about GatorPlate",
    prototype: "Student-built prototype — not an official SF State, county, or CalFresh service.",
    skip: "Skip to main content",
    "lang.label": "Language",
    // The pitch sections under the first screen (A7.2): the gap, how it works (the seven-step pipeline), why the AI is
    // essential (and the checks behind it), responsibility (the eight-risk matrix), six programs, try it.
    "gap.kicker": "The gap at SF State",
    "gap.title": "About 3,450 SF State students likely qualify for CalFresh and aren't getting it.",
    "gap.about": "about",
    "gap.students": "students",
    "gap.upto": "up to",
    "gap.year": "a year",
    "gap.money": "Up to $12.7 million a year in food money — CalFresh alone, at the one-person maximum.",
    "gap.eligible": "≈6,030 likely eligible",
    "gap.receiving": "≈2,580 already receive it",
    "gap.missing": "≈3,450 not yet",
    "gap.method": "Estimate based on UC eligibility research applied to SF State enrollment: 33% of UC undergraduates and 7% of UC graduate students were eligible for CalFresh (California Policy Lab, Fall 2019 data, published Aug 2024), applied to SF State's 17,607 undergraduates and 3,114 graduate students (Fall 2025), minus the 14.3% of SF State undergraduates who already received CalFresh in 2023–24 (California Policy Lab, Aug 2026) and graduate students at the UC rate. \"Up to\" assumes the $306 one-person maximum for 12 months; the average benefit is lower.",
    "gap.sources": "Sources",
    "gap.src1": "Enrollment: 17,607 undergraduates and 3,114 graduate students, Fall 2025 (SF State Facts).",
    "gap.src2": "Eligible: 33% of UC undergraduates and 7% of UC graduate students, Fall 2019 (California Policy Lab, \"Filling the Gap,\" Aug 2024) → ≈6,030 at SF State.",
    "gap.src3": "Already receiving: 14.3% of SF State undergraduates, 2023–24 (California Policy Lab, Aug 2026); graduate students at the UC rate of 27% of those eligible → ≈2,580.",
    "gap.src4": "Up to $306/month: CalFresh maximum for one person from Oct 1, 2026 (CDSS ACIN I-40-26).",
    "gap.src5": "Average is lower: participating UC undergraduates averaged $161/month when the maximum was $194 (California Policy Lab, Feb 2025) — about $10.5M/yr at that ratio.",
    "gap.src6": "Graduate students are estimated with UC rates (7% eligible, 27% of them receiving). SF State's own data show 13.6% of graduate students already receive CalFresh — higher than this method assumes — so the ~160 graduate students in this estimate are the least certain part.",
    "gap.src7": "Likely conservative: since June 1, 2026, half-time CSU bachelor's students meet the student rule (CDSS ACL 26-25); the 2019 rate predates this.",
    "how.kicker": "How it works",
    "how.title": "The AI listens. A dated rules table decides. A person confirms.",
    "how.lede": "A short conversation instead of a screening form. Here is what happens to every sentence a student says.",
    "how.legend": "Highlighted: the steps where AI does the work",
    "how.chip.student": "Student",
    "how.chip.lm": "AI · Language model",
    "how.chip.planner": "AI · Decision planner (code)",
    "how.chip.code": "Code",
    "how.chip.person": "Person",
    "how.1.h": "You talk",
    "how.1.p": "Call from any phone (English), or talk or type in your browser (English or Spanish). Your words become text — GatorPlate never receives audio.",
    "how.2.h": "The AI understands",
    "how.2.p": "A language model turns free speech — any wording, corrections, several answers at once, English or Spanish — into the exact facts the rules need, and flags what it isn't sure of.",
    "how.2.noise": "Background noise and half-finished words are asked again, not saved.",
    "how.3.h": "Checked against your words",
    "how.3.p": "Every fact must quote the student's exact words; a number the student never said is dropped. A rule parser reads every sentence too — if it disagrees on an amount, GatorPlate asks.",
    "how.4.h": "Rules decide",
    "how.4.p": "A dated table of this year's CalFresh rules (Oct 2026 – Sep 2027) computes every dollar, with a source for each step. The AI never does the math.",
    "how.5.h": "Asks only what matters",
    "how.5.p": "Before each optional question, GatorPlate re-runs the rules for every possible answer. It asks only if the answer could change the result or move the estimate by more than $50 a month.",
    "how.6.h": "A person confirms",
    "how.6.p": "Anything uncertain becomes a highlighted line in the coordinator's console, and a case can't be marked reviewed until every line is checked. The county decides eligibility.",
    "how.7.h": "Your card",
    "how.7.p": "The estimate, your answers for the application, documents to bring, interview prep — and the other help CalFresh may open.",
    "care.yl.tag": "To check",
    "care.yl.text": "Monthly rent — “around 800, I think”",
    "why.kicker": "Why the AI is essential",
    "why.title": "Not a chatbot add-on. Without the AI, the call is a phone tree.",
    "why.demo.label": "Example",
    "why.demo.quote": "“I make like eighteen an hour, maybe fifteen hours a week”",
    "why.demo.pay": "Hourly pay",
    "why.demo.hours": "Hours a week",
    "why.demo.check": "to confirm",
    "why.1.h": "A conversation instead of a form",
    "why.1.p": "Students don't talk in form fields. One sentence becomes hourly pay, hours and a flag to confirm. Without the model, the call falls back to closed yes-or-no questions — a phone tree.",
    "why.2.h": "Every fact is tied to the student's words",
    "why.2.p": "The AI must quote what the student said for every value. A quote that isn't in the student's words turns the value yellow; a number the student never said is dropped. The coordinator sees the quote next to the field.",
    "why.3.h": "It knows when to ask a person",
    "why.3.p": "It marks hedges, ranges and contradictions as unsure instead of guessing. It also hears what isn't an answer: a request for a person, a prompt-injection trick, or a crisis — which gets 988 and 911 at once.",
    "edge.title": "Built to be checked",
    "edge.2.h": "Two readers on every sentence.",
    "edge.2.p": "A language model and a rule parser read each turn. If they disagree on an amount, or “fifteen” could be “fifty,” the student is asked. If the model is slow or down, the call keeps going on the parser with closed questions.",
    "edge.3.h": "Grounded, not generated.",
    "edge.3.p": "The model returns facts only — never a sentence and never a number of its own. Every reply comes from a reviewed sentence bank and passes an output guard.",
    "edge.4.h": "Value-of-information questions.",
    "edge.4.p": "The planner measures what each unknown could change and skips the rest — about 6 questions per call in our simulated-student tests.",
    "edge.6.h": "Attacked on purpose.",
    "edge.6.p": "3,000+ automated tests, 28 end-to-end scripts and 38 adversarial scripts — including prompt injection, a spoken Social Security number and a crisis in Spanish.",
    "edge.note": "Tests are text-level with simulated students, not real students or real speech recognition.",
    "care.kicker": "Responsible by design",
    "care.title": "Eight risks we planned for, and what we do about each.",
    "care.sub": "GatorPlate gives estimates, never decisions. The AI listens and flags what it isn't sure of; it never sets a number or makes a decision. Numbers come from a dated rules table, and a person checks anything uncertain.",
    "care.caption": "Risks, what GatorPlate does today, and what comes before real students",
    "care.col.risk": "Risk",
    "care.col.today": "What GatorPlate does today",
    "care.col.next": "Before real students",
    "care.more": "More",
    "care.note": "Tested with simulated students and scripts, not real students or real speech recognition. Not an official SF State, county or CalFresh service.",
    "care.r1.h": "Privacy",
    "care.r1.w": "Income, rent and household details are sensitive.",
    "care.r1.key": "Call audio isn't recorded.",
    "care.r1.do": "We keep your answers with short quotes, not the conversation, and you can delete them from your card or by saying “delete my data.” GatorPlate never receives your phone number and never asks your name. The language model gets only the current question and your last few sentences, with ID-like digits removed.",
    "care.r1.next": "Cases auto-delete after 30 days.",
    "care.r2.h": "Security",
    "care.r2.w": "Someone talks the AI into a bigger number, or data leaks.",
    "care.r2.key": "The AI can't set a number.",
    "care.r2.do": "Its output is schema-checked and every answer must quote the student's exact words. Phone requests are signed, the coordinator console needs a passcode, card links are unguessable and expire, requests are rate-limited, and logs hold no conversation content. Pages load nothing from third parties.",
    "care.r2.next": "SF State's data and security review.",
    "care.r3.h": "Accessibility",
    "care.r3.w": "Students who can't use an app, can't see, can't hear or can't speak are left out.",
    "care.r3.key": "Works from any phone, with no app, no smartphone and no login.",
    "care.r3.do": "The card code is spoken. On the web you can always type instead of talk. The card targets WCAG 2.2 AA: 4.5:1 text contrast, keyboard use, screen-reader labels, 48 px tap targets, 200% zoom.",
    "care.r3.next": "SF State's accessibility review. Calls for students who can't hear aren't specially handled yet; typing on the web works.",
    "care.r4.h": "Data accuracy",
    "care.r4.w": "CalFresh rules changed three times in 2026; old numbers mislead.",
    "care.r4.key": "One dated rules table, every row with its source.",
    "care.r4.do": "The engine matches 78 hand-computed cases and an independent hand model on 4,000 random fact sets, with 0 mismatches. No estimate outside the table's dates.",
    "care.r4.next": "Re-check every October 1 and after each state letter.",
    "care.r5.h": "Bias & fairness",
    "care.r5.w": "Spanish speakers or accents get worse results.",
    "care.r5.key": "One rules engine for both languages.",
    "care.r5.do": "The same facts must give the same result. In 59 scripted simulated-student calls, run with a stand-in for the language model, English (48/48) and Spanish (11/11) all reached the right result. A native speaker reviewed the app's Spanish text, and risky numbers (“fifteen or fifty?”) are read back and confirmed.",
    "care.r5.next": "Testing real accents on real phone lines.",
    "care.r6.h": "Consent & law",
    "care.r6.w": "California requires every party's consent to record or listen in on a confidential call.",
    "care.r6.key": "Saying no ends the call.",
    "care.r6.do": "Before any question, the call says it's a student-built AI, not an official SF State service, that an AI turns speech into text, and that the audio isn't recorded. Then it asks: say yes or press one. “Are you a robot?” and “Is this recorded?” get a true answer anytime.",
    "care.r6.next": "Legal review of the consent wording; providers' data terms in writing.",
    "care.r7.h": "Over-reliance",
    "care.r7.w": "A student or coordinator treats an AI guess as a decision.",
    "care.r7.key": "Every result says “estimate — the county decides.”",
    "care.r7.do": "GatorPlate never gives a “no” on eligibility. Anything uncertain becomes a yellow line, and the server won't mark a case reviewed until a person checks each one. It never applies or signs for anyone. In a crisis it gives 988 and 911 right away.",
    "care.r7.next": "Weekly review with the CalFresh coordinator.",
    "care.r8.h": "Immigration safety",
    "care.r8.w": "Students in mixed-status families fear sharing anything.",
    "care.r8.key": "GatorPlate never asks for a Social Security number or immigration status.",
    "care.r8.do": "If a student brings status up, it isn't stored or kept as context; GatorPlate points them to the coordinator or a legal aid office. Digits that look like an SSN or card number are removed before the AI sees the text or anything is saved.",
    "care.r8.next": "Wording checked with campus and legal-aid partners.",
    "prog.kicker": "Six programs",
    "prog.sofar": "The numbers above count CalFresh alone.",
    "prog.title": "CalFresh is the key.",
    "prog.sub": "It can open more help this year: Medi-Cal, Clipper START, PG&E CARE, California LifeLine and tax credits.",
    "prog.tax": "Tax credits",
    "prog.check": "We check six programs. For Maria, four save money, one is health coverage, and one is a maybe at tax time.",
    "prog.who": "Maria, a sample student from our demo",
    "prog.alone": "CalFresh alone",
    "prog.upto": "up to about",
    "prog.transit": "Clipper START — transit",
    "prog.phone": "California LifeLine — phone",
    "prog.phone.amt": "up to $220",
    "prog.energy": "PG&E CARE — energy",
    "prog.total": "Total a year, up to about",
    "prog.coverage": "+ health coverage",
    "prog.maybe": "maybe $200 — not counted",
    "prog.note": "Estimates from dated tables, computed by code, not by the AI. Each agency decides.",
    "try.kicker": "Try it",
    "try.title": "Check the money you may be missing.",
    "try.sub_phone": "A few minutes. Free. Call in English, or talk in your browser in English or Spanish.",
    "try.sub_web": "A few minutes. Free. Talk in your browser in English or Spanish.",
  },
  es: {
    title: "GatorPlate",
    headline_phone: "¡Revisa el dinero que quizá te falta reclamar, por teléfono o en tu navegador!",
    headline_web: "Revisa el dinero que quizá te falta reclamar en tu navegador.",
    sub: "Estudiantes de SF State: CalFresh da hasta $306 al mes a una persona para comida, y puede abrir más ayudas. Unos minutos. Gratis. Solo son estimados: cada agencia decide.",
    talk: "Habla en tu navegador",
    call: "Llama al {number}",
    phone_note: "La línea telefónica es solo en inglés.",
    about: "Cómo funciona y uso responsable de la IA (en inglés)",
    console: "Para la coordinación (en inglés)",
    "trust.label": "Privacidad y límites",
    "trust.recorded": "No se graba el audio",
    "trust.ssn": "Nunca te pide tu número de Seguro Social ni tu estatus migratorio",
    "trust.estimate": "Solo son estimados: cada agencia decide",
    "more.label": "Más sobre GatorPlate",
    prototype: "Prototipo hecho por estudiantes; no es un servicio oficial de SF State, del condado ni de CalFresh.",
    skip: "Ir al contenido",
    "lang.label": "Idioma",
    "gap.kicker": "La brecha en SF State",
    "gap.title": "Unos 3,450 estudiantes de SF State probablemente reúnen los requisitos de CalFresh y no lo reciben.",
    "gap.about": "unos",
    "gap.students": "estudiantes",
    "gap.upto": "hasta",
    "gap.year": "al año",
    "gap.money": "Hasta $12.7 millones al año en dinero para comida — solo CalFresh, con el máximo para una persona.",
    "gap.eligible": "≈6,030 probablemente elegibles",
    "gap.receiving": "≈2,580 ya lo reciben",
    "gap.missing": "≈3,450 todavía no",
    "gap.method": "Estimado basado en investigación sobre elegibilidad en la UC, aplicado a la matrícula de SF State: el 33% de los estudiantes de licenciatura y el 7% de los de posgrado de la UC eran elegibles para CalFresh (California Policy Lab, datos de otoño de 2019, publicado en agosto de 2024), aplicado a los 17,607 estudiantes de licenciatura y 3,114 de posgrado de SF State (otoño de 2025), menos el 14.3% de los estudiantes de licenciatura de SF State que ya recibieron CalFresh en 2023–24 (California Policy Lab, agosto de 2026) y los de posgrado con la tasa de la UC. «Hasta» supone el máximo de $306 para una persona durante 12 meses; el beneficio promedio es menor.",
    "gap.sources": "Fuentes",
    "gap.src1": "Matrícula: 17,607 estudiantes de licenciatura y 3,114 de posgrado, otoño de 2025 (SF State Facts).",
    "gap.src2": "Elegibles: 33% de los estudiantes de licenciatura y 7% de los de posgrado de la UC, otoño de 2019 (California Policy Lab, «Filling the Gap», agosto de 2024) → ≈6,030 en SF State.",
    "gap.src3": "Ya lo reciben: 14.3% de los estudiantes de licenciatura de SF State, 2023–24 (California Policy Lab, agosto de 2026); los de posgrado con la tasa de la UC, 27% de los elegibles → ≈2,580.",
    "gap.src4": "Hasta $306 al mes: máximo de CalFresh para una persona desde el 1 de octubre de 2026 (CDSS ACIN I-40-26).",
    "gap.src5": "El promedio es menor: los estudiantes de licenciatura de la UC que participaban recibían en promedio $161 al mes cuando el máximo era $194 (California Policy Lab, febrero de 2025), unos $10.5 millones al año con esa proporción.",
    "gap.src6": "Los estudiantes de posgrado se estiman con las tasas de la UC (7% elegibles, 27% de ellos lo reciben). Los datos de SF State muestran que el 13.6% de sus estudiantes de posgrado ya recibe CalFresh — más de lo que supone este método —, así que los ~160 estudiantes de posgrado de este estimado son la parte menos segura.",
    "gap.src7": "Probablemente conservador: desde el 1 de junio de 2026, los estudiantes de licenciatura de la CSU a medio tiempo cumplen la regla para estudiantes (CDSS ACL 26-25); la tasa de 2019 es anterior.",
    "how.kicker": "Cómo funciona",
    "how.title": "La IA escucha. Una tabla de reglas con fecha decide. Una persona confirma.",
    "how.lede": "Una conversación corta en lugar de un formulario. Esto es lo que pasa con cada frase que dice el estudiante.",
    "how.legend": "Resaltado: los pasos donde trabaja la IA",
    "how.chip.student": "Estudiante",
    "how.chip.lm": "IA · Modelo de lenguaje",
    "how.chip.planner": "IA · Planificador de decisiones (código)",
    "how.chip.code": "Código",
    "how.chip.person": "Persona",
    "how.1.h": "Hablas",
    "how.1.p": "Llama desde cualquier teléfono (inglés), o habla o escribe en tu navegador (inglés o español). Tus palabras se vuelven texto: GatorPlate nunca recibe audio.",
    "how.2.h": "La IA entiende",
    "how.2.p": "Un modelo de lenguaje convierte el habla libre —cualquier forma de decirlo, correcciones, varias respuestas a la vez, en inglés o en español— en los datos exactos que necesitan las reglas, y marca lo que no tiene claro.",
    "how.2.noise": "El ruido de fondo y las palabras a medias se vuelven a preguntar, no se guardan.",
    "how.3.h": "Comprobado con tus palabras",
    "how.3.p": "Cada dato debe citar las palabras exactas del estudiante; un número que el estudiante no dijo se descarta. Un analizador de reglas también lee cada frase; si no coincide en una cantidad, GatorPlate pregunta.",
    "how.4.h": "Las reglas deciden",
    "how.4.p": "Una tabla con fecha de las reglas de CalFresh de este año (oct. 2026 – sep. 2027) calcula cada dólar, con la fuente de cada paso. La IA nunca hace las cuentas.",
    "how.5.h": "Solo pregunta lo que importa",
    "how.5.p": "Antes de cada pregunta opcional, GatorPlate vuelve a calcular las reglas con cada respuesta posible. Solo pregunta si la respuesta podría cambiar el resultado o mover el estimado más de $50 al mes.",
    "how.6.h": "Una persona confirma",
    "how.6.p": "Todo lo dudoso aparece resaltado en la consola de la coordinación. Un caso no se puede marcar como revisado hasta revisar cada línea. El condado decide la elegibilidad.",
    "how.7.h": "Tu tarjeta",
    "how.7.p": "El estimado, tus respuestas para la solicitud, los documentos que debes llevar, la preparación para la entrevista y otras ayudas que CalFresh puede abrir.",
    "care.yl.tag": "Por revisar",
    "care.yl.text": "Renta mensual — «unos 800, creo»",
    "why.kicker": "Por qué la IA es esencial",
    "why.title": "No es un chatbot añadido. Sin la IA, la llamada es un menú telefónico.",
    "why.demo.label": "Ejemplo",
    "why.demo.quote": "«Gano como dieciocho la hora, unas quince horas a la semana»",
    "why.demo.pay": "Pago por hora",
    "why.demo.hours": "Horas a la semana",
    "why.demo.check": "por confirmar",
    "why.1.h": "Una conversación en lugar de un formulario",
    "why.1.p": "Los estudiantes no hablan en campos de formulario. Una frase se convierte en pago por hora, horas y una marca para confirmar. Sin el modelo, la llamada vuelve a preguntas cerradas de sí o no, como un menú telefónico.",
    "why.2.h": "Cada dato está ligado a las palabras del estudiante",
    "why.2.p": "La IA debe citar lo que dijo el estudiante para cada valor. Si la cita no está en sus palabras, el valor queda en amarillo; un número que el estudiante no dijo se descarta. La coordinación ve la cita junto al campo.",
    "why.3.h": "Sabe cuándo pedir ayuda a una persona",
    "why.3.p": "Marca las dudas, los rangos y las contradicciones como inciertos en lugar de adivinar. También oye lo que no es una respuesta: pedir hablar con una persona, un truco de inyección de instrucciones o una crisis, que recibe el 988 y el 911 de inmediato.",
    "edge.title": "Hecho para comprobarse",
    "edge.2.h": "Dos lectores en cada frase.",
    "edge.2.p": "Un modelo de lenguaje y un analizador de reglas leen cada turno. Si no coinciden en una cantidad, o si «quince» podría ser «cincuenta», se le pregunta al estudiante. Si el modelo tarda o falla, la llamada sigue con el analizador y preguntas cerradas.",
    "edge.3.h": "Basado en lo dicho, no inventado.",
    "edge.3.p": "El modelo solo devuelve datos: nunca una frase ni un número propio. Cada respuesta sale de un banco de frases revisado y pasa un filtro de salida.",
    "edge.4.h": "Preguntas según el valor de la información.",
    "edge.4.p": "El planificador mide lo que cada dato desconocido podría cambiar y omite el resto: unas 6 preguntas por llamada en nuestras pruebas con estudiantes simulados.",
    "edge.6.h": "Atacado a propósito.",
    "edge.6.p": "Más de 3,000 pruebas automáticas, 28 guiones de principio a fin y 38 guiones adversarios, entre ellos la inyección de instrucciones, un número de Seguro Social dicho en voz alta y una crisis en español.",
    "edge.note": "Las pruebas son a nivel de texto con estudiantes simulados, no con estudiantes reales ni reconocimiento de voz real.",
    "care.kicker": "Responsable desde el diseño",
    "care.title": "Ocho riesgos que previmos, y lo que hacemos con cada uno.",
    "care.sub": "GatorPlate da estimados, nunca decisiones. La IA escucha y marca lo que no tiene claro; nunca fija un número ni toma una decisión. Los números salen de una tabla de reglas con fecha, y una persona revisa todo lo dudoso.",
    "care.caption": "Riesgos, lo que GatorPlate hace hoy y lo que falta antes de usarlo con estudiantes reales",
    "care.col.risk": "Riesgo",
    "care.col.today": "Lo que GatorPlate hace hoy",
    "care.col.next": "Antes de usarlo con estudiantes reales",
    "care.more": "Más",
    "care.note": "Probado con estudiantes simulados y guiones, no con estudiantes reales ni con reconocimiento de voz real. No es un servicio oficial de SF State, del condado ni de CalFresh.",
    "care.r1.h": "Privacidad",
    "care.r1.w": "Los ingresos, la renta y el hogar son datos sensibles.",
    "care.r1.key": "El audio de la llamada no se graba.",
    "care.r1.do": "Guardamos tus respuestas con citas cortas, no la conversación, y puedes borrarlas desde tu tarjeta o diciendo «borra mis datos». GatorPlate nunca recibe tu número de teléfono y nunca pide tu nombre. El modelo de lenguaje solo recibe la pregunta actual y tus últimas frases, sin dígitos de identificación.",
    "care.r1.next": "Los casos se borran solos a los 30 días.",
    "care.r2.h": "Seguridad",
    "care.r2.w": "Alguien convence a la IA de dar un número mayor, o se filtran datos.",
    "care.r2.key": "La IA no puede fijar un número.",
    "care.r2.do": "Su salida se valida contra un esquema y cada respuesta debe citar las palabras exactas del estudiante. Las solicitudes telefónicas van firmadas, la consola pide un código de acceso, los enlaces de la tarjeta no se pueden adivinar y caducan, hay límites de solicitudes y los registros no guardan el contenido de la conversación. Las páginas no cargan nada de terceros.",
    "care.r2.next": "Revisión de datos y seguridad de SF State.",
    "care.r3.h": "Accesibilidad",
    "care.r3.w": "Quedan fuera quienes no usan apps, no ven, no oyen o no pueden hablar.",
    "care.r3.key": "Funciona desde cualquier teléfono, sin app, sin smartphone y sin cuenta.",
    "care.r3.do": "El código de la tarjeta se dice en voz alta. En la web siempre puedes escribir en lugar de hablar. La tarjeta apunta a WCAG 2.2 AA: contraste de texto 4.5:1, uso con teclado, etiquetas para lectores de pantalla, botones de 48 px y zoom al 200 %.",
    "care.r3.next": "Revisión de accesibilidad de SF State. Las llamadas de estudiantes que no oyen aún no tienen un trato especial; en la web se puede escribir.",
    "care.r4.h": "Exactitud de datos",
    "care.r4.w": "Las reglas de CalFresh cambiaron tres veces en 2026; los números viejos confunden.",
    "care.r4.key": "Una sola tabla de reglas con fecha, con la fuente en cada fila.",
    "care.r4.do": "El motor coincide con 78 casos calculados a mano y con un modelo independiente en 4,000 casos al azar, con 0 diferencias. No da estimados fuera de las fechas de la tabla.",
    "care.r4.next": "Revisión cada 1 de octubre y tras cada carta del estado.",
    "care.r5.h": "Sesgo y equidad",
    "care.r5.w": "Quien habla español o tiene acento recibe peores resultados.",
    "care.r5.key": "Un mismo motor de reglas para los dos idiomas.",
    "care.r5.do": "Los mismos datos deben dar el mismo resultado. En 59 llamadas guionizadas con estudiantes simulados, con un sustituto del modelo de lenguaje, inglés (48/48) y español (11/11) llegaron todas al resultado correcto. Una persona hispanohablante nativa revisó el texto en español de la app, y los números dudosos («¿quince o cincuenta?») se repiten y se confirman.",
    "care.r5.next": "Pruebas con acentos reales en llamadas reales.",
    "care.r6.h": "Consentimiento y ley",
    "care.r6.w": "California exige el consentimiento de todas las partes para grabar o escuchar una llamada confidencial.",
    "care.r6.key": "Si dices que no, la llamada termina.",
    "care.r6.do": "Antes de cualquier pregunta, la llamada dice que es una IA hecha por estudiantes, no un servicio oficial de SF State, que una IA convierte la voz en texto y que el audio no se graba. Luego pregunta: di que sí o marca uno. «¿Eres un robot?» y «¿Se graba esto?» reciben una respuesta verdadera en cualquier momento.",
    "care.r6.next": "Revisión legal del texto de consentimiento; condiciones de datos de los proveedores por escrito.",
    "care.r7.h": "Exceso de confianza",
    "care.r7.w": "Un estudiante o la coordinación toma una suposición de la IA como una decisión.",
    "care.r7.key": "Cada resultado dice «estimado: el condado decide».",
    "care.r7.do": "GatorPlate nunca da un «no» sobre la elegibilidad. Todo lo dudoso se marca en amarillo, y el servidor no deja marcar un caso como revisado hasta que una persona revise cada línea. Nunca presenta ni firma solicitudes por nadie. En una crisis, da el 988 y el 911 de inmediato.",
    "care.r7.next": "Revisión semanal con la coordinación de CalFresh.",
    "care.r8.h": "Seguridad migratoria",
    "care.r8.w": "Estudiantes de familias con estatus mixto temen compartir datos.",
    "care.r8.key": "GatorPlate nunca pide el número de Seguro Social ni el estatus migratorio.",
    "care.r8.do": "Si un estudiante menciona su estatus, no se guarda ni se usa como contexto; GatorPlate lo remite a la coordinación o a una oficina de ayuda legal. Los dígitos que parecen un número de Seguro Social o de tarjeta se borran antes de que la IA vea el texto o de guardar nada.",
    "care.r8.next": "Revisar el texto con aliados del campus y de ayuda legal.",
    "prog.kicker": "Seis programas",
    "prog.sofar": "Las cifras de arriba cuentan solo CalFresh.",
    "prog.title": "CalFresh es la llave.",
    "prog.sub": "Puede abrir más ayudas este año: Medi-Cal, Clipper START, PG&E CARE, California LifeLine y créditos fiscales.",
    "prog.tax": "Créditos fiscales",
    "prog.check": "Revisamos seis programas. Para Maria, cuatro ahorran dinero, uno es cobertura médica y uno es un «quizá» al declarar impuestos.",
    "prog.who": "Maria, una estudiante de ejemplo de nuestra demo",
    "prog.alone": "Solo CalFresh",
    "prog.upto": "hasta unos",
    "prog.transit": "Clipper START — transporte",
    "prog.phone": "California LifeLine — teléfono",
    "prog.phone.amt": "hasta $220",
    "prog.energy": "PG&E CARE — energía",
    "prog.total": "Total al año, hasta unos",
    "prog.coverage": "+ cobertura médica",
    "prog.maybe": "quizá $200 — no se cuenta",
    "prog.note": "Estimados de tablas con fecha, calculados por código, no por la IA. Cada agencia decide.",
    "try.kicker": "Pruébalo",
    "try.title": "Revisa el dinero que quizá te falta reclamar.",
    "try.sub_phone": "Unos minutos. Gratis. Llama en inglés, o habla en tu navegador en inglés o español.",
    "try.sub_web": "Unos minutos. Gratis. Habla en tu navegador en inglés o español.",
  },
};

export function resolveLang(search = "", navLang = "") {
  const q = new URLSearchParams(search).get("lang");
  if (q === "en" || q === "es") return q;
  return String(navLang || "").toLowerCase().startsWith("es") ? "es" : "en";
}

// The headline as display lines: the hook (up to "—" or the first comma), then the channel part, so a break never
// splits "you may be / missing". No-break spaces keep the dash on the hook's line (no line starts with "—") and the
// channel's last three words together ("by phone or / in your browser", never "… or in / your browser"). Only spaces
// change; the words are the strings above.
export function headlineParts(text) {
  const t = String(text).replace(/ —/g, "\u00a0—");
  const m = t.match(/^(.*?(?:\u00a0—|,))\s+(\S.*)$/);
  if (!m) return [t];
  const words = m[2].split(" ");
  const tail = words.length > 3 ? words.splice(-3).join("\u00a0") : null;
  return [m[1], tail ? [...words, tail].join(" ") : m[2]];
}

// A big pitch title as display lines, one per sentence ("The AI listens." / "A rules table decides." / ...).
export function sentenceLines(text) {
  return String(text).split(/(?<=[.!?])\s+/).filter(Boolean);
}

// Everything the page shows, from PublicInfo (or null when it could not be loaded) and the language.
export function landingView(info, lang, { fixtures = false } = {}) {
  const l = lang === "es" ? "es" : "en";
  const s = LANDING_STRINGS[l];
  const raw = info && typeof info.demo_phone_display === "string" ? info.demo_phone_display.trim() : "";
  const digits = raw.replace(/\D/g, "");
  const phone = raw
    ? { text: fill(s.call, { number: raw }), href: digits.length >= 10 ? telHref(raw) : null, note: s.phone_note }
    : null;
  return {
    lang: l,
    headline: phone ? s.headline_phone : s.headline_web,
    phone,
    trySub: phone ? s["try.sub_phone"] : s["try.sub_web"],   // 06 Try it: mentions the call only when there is one
    // The one filled button on each screen: the call when there is a number, except on the Spanish page, where the
    // English-only phone line stays first but outlined and talking in the browser (in Spanish) is the filled one.
    primary: phone && l !== "es" ? "phone" : "talk",
    talkHref: fixtures ? `/talk/?fixtures=1&lang=${l}` : `/talk?lang=${l}`,
    aboutHref: fixtures ? "/about/?fixtures=1" : "/about",
    consoleHref: fixtures ? "/console/?fixtures=1" : "/console",
    strings: s,
  };
}

// ------------------------------------------------------------------------------------------------ the page

let current = { info: null, lang: "en", fixtures: false };

function paint() {
  const v = landingView(current.info, current.lang, { fixtures: current.fixtures });
  const s = v.strings;
  const $ = (id) => document.getElementById(id);
  document.documentElement.lang = v.lang;
  document.title = s.title;
  for (const node of document.querySelectorAll("[data-t]")) {
    const text = s[node.dataset.t];
    if (typeof text !== "string") continue;
    if (node.hasAttribute("data-lines")) {   // one display line per sentence
      if (node.textContent === text && node.children.length) continue;
      const lines = sentenceLines(text).map((part) => {
        const span = document.createElement("span");
        span.className = "pitch__line";
        span.textContent = part;
        return span;
      });
      node.replaceChildren(...lines.flatMap((span, i) => (i ? [" ", span] : [span])));
    } else if (node.textContent !== text) node.textContent = text;
  }
  for (const node of document.querySelectorAll("[data-t-label]")) node.setAttribute("aria-label", s[node.dataset.tLabel]);
  for (const b of document.querySelectorAll(".langswitch__btn")) {
    b.setAttribute("aria-pressed", String(b.dataset.lang === v.lang));
  }
  const lines = headlineParts(v.headline).map((part) => {
    const span = document.createElement("span");
    span.className = "hero__line";
    span.textContent = part;
    return span;
  });
  $("headline").replaceChildren(...lines.flatMap((span, i) => (i ? [" ", span] : [span])));
  if ($("try-sub").textContent !== v.trySub) $("try-sub").textContent = v.trySub;
  for (const pre of ["", "cta-"]) {
    $(`${pre}talk-link`).setAttribute("href", v.talkHref);
    $(`${pre}about-link`).setAttribute("href", v.aboutHref);
    $(`${pre}console-link`).setAttribute("href", v.consoleHref);
    const link = $(`${pre}phone-link`);
    const note = $(`${pre}phone-note`);
    link.hidden = !v.phone;
    note.hidden = !(v.phone && v.phone.note);
    link.classList.toggle("btn--primary", v.primary === "phone");
    $(`${pre}talk-link`).classList.toggle("btn--primary", v.primary === "talk");
    if (v.phone) {
      $(`${pre}phone-text`).textContent = v.phone.text;
      if (v.phone.href) link.setAttribute("href", v.phone.href);
      else link.removeAttribute("href");
      note.textContent = v.phone.note;
    }
  }
}

// Calm reveal of the pitch sections while scrolling: only with motion allowed and IntersectionObserver present;
// otherwise (and before this runs) everything is simply shown.
function reveal() {
  const calm = window.matchMedia && window.matchMedia("(prefers-reduced-motion: no-preference)").matches;
  if (!calm || typeof IntersectionObserver !== "function") return;
  const sections = [...document.querySelectorAll(".pitch, .split")];   // the bar grows when it is itself in view
  const io = new IntersectionObserver((entries) => {
    for (const e of entries) {
      if (!e.isIntersecting) continue;
      e.target.classList.add("is-in");
      io.unobserve(e.target);
    }
  }, { rootMargin: "0px 0px -12% 0px", threshold: 0 });
  for (const el of sections) io.observe(el);
  document.documentElement.classList.add("js-reveal");
}

// 04 risk matrix: on a wide screen every row's details are open (the table has room); on a phone each card shows its
// key line and opens "More" on tap. Without JS the details stay closed and the key lines still carry the matrix.
function wideMore() {
  if (!window.matchMedia) return;
  const wide = window.matchMedia("(min-width: 64em)");
  const apply = () => { for (const d of document.querySelectorAll("details[data-more]")) d.open = wide.matches; };
  apply();
  if (wide.addEventListener) wide.addEventListener("change", apply);
}

// Re-render with other public info (also handy from the page console to check the number's layout).
export function show(info) {
  current = { ...current, info };
  if (typeof document !== "undefined") paint();
}

async function init() {
  const { fetchJSON, FIXTURES } = await import("./shared/api.js");
  const browserLang = (navigator.languages || [])[0] || navigator.language;
  current = { info: null, lang: resolveLang(location.search, browserLang), fixtures: FIXTURES };
  for (const b of document.querySelectorAll(".langswitch__btn")) {
    b.addEventListener("click", () => {
      current = { ...current, lang: b.dataset.lang };
      try {
        const url = new URL(location.href);
        url.searchParams.set("lang", current.lang);
        history.replaceState(history.state, "", url);
      } catch { /* the address stays as it was */ }
      paint();
    });
  }
  paint();
  wideMore();
  reveal();
  try {
    current = { ...current, info: await fetchJSON("/api/public/info", { lang: current.lang }) };
  } catch {
    current = { ...current, info: null };
  }
  paint();
}

if (typeof document !== "undefined" && document.getElementById("headline")) init();
