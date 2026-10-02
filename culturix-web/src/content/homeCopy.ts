// Homepage copy for the four public languages. A plain module (not the client LocaleProvider)
// because the homepage is a server component; it picks the locale from the same
// `culturix_language` cookie the language switcher sets.
//
// Viewer-first: no plans, pricing, sign-up or creator features. Every claim here must stay true
// of the live product (see CLAUDE.md, /world redesign note).

export type HomeLocale = "en" | "fr" | "de" | "es";

const EN = {
  hero: {
    badge: "Culturix World",
    title: "The world, explained in short videos",
    titleAccent: "with a sense of humour",
    body: "An AI-made video encyclopedia of places, natural phenomena, species and technology. Each video is short and made from real sources you can check.",
    ctaPrimary: "Start watching",
    ctaSecondary: "How it works",
    note: "Free to watch. No account needed.",
    latest: "Latest video",
  },
  stats: { videos: "videos published", countries: "countries with videos", themes: "themes to explore", free: "Free", freeLabel: "to watch, no account" },
  latest: { title: "Fresh from around the world", body: "The newest videos in the encyclopedia.", seeAll: "See all videos" },
  themes: {
    title: "Pick a theme",
    body: "Or follow a place: every country with videos has its own page with quick facts and what people there are talking about today.",
    byPlace: "Explore by place",
    items: {
      place: { name: "Places", desc: "Cities, landmarks and World Heritage sites" },
      phenomenon: { name: "Phenomena", desc: "Natural wonders and strange events" },
      species: { name: "Species", desc: "Animals and plants worth meeting" },
      tech: { name: "Technology", desc: "Inventions and what they changed" },
      genz: { name: "Gen-Z", desc: "Internet culture, explained" },
      custom: { name: "More", desc: "Everything that doesn't fit a box" },
    } as Record<string, { name: string; desc: string }>,
  },
  how: {
    eyebrow: "How it works",
    title: "Real sources in, short videos out",
    body: "Plenty of AI video is made up. Ours starts from a real source and shows its work.",
    steps: [
      { title: "It starts from a real source", desc: "Each video begins with a Wikipedia article or a UNESCO World Heritage listing. Nothing is invented from thin air." },
      { title: "AI writes it, then checks itself", desc: "The script is written only from that source. A second pass flags any claim the source doesn't support, and it gets rewritten." },
      { title: "A person reviews it", desc: "New videos pass a quality check and a human review before they are published, with a link back to the source." },
    ],
    sourcesLabel: "Sources",
  },
  trust: {
    eyebrow: "Checked, not guessed",
    title: "Short video, without the made-up facts",
    body: "Short videos are how many people learn about the world now, and too many of them are confidently wrong. Culturix keeps a paper trail so you can check it yourself.",
    points: [
      "Videos link to the source they were made from",
      "Scripts are checked against that source",
      "New videos are reviewed by a person before publishing",
      "Read the transcript in your own language",
    ],
  },
  faq: {
    title: "Questions",
    items: [
      { q: "Is Culturix free?", a: "Yes. Watching is free and you don't need an account." },
      { q: "Who makes the videos?", a: "They are generated with AI from a real source and checked against it. New videos are also reviewed by a person before they are published." },
      { q: "How accurate are they?", a: "Each script is checked against its source, and videos link to that source so you can verify things yourself." },
      { q: "Why the humour?", a: "Facts stick better when they're fun. The tone is light; the facts come from the source." },
      { q: "Can I watch in my language?", a: "The site is available in English, French, German and Spanish, and each video's transcript can be translated into more languages." },
    ],
  },
  cta: { title: "Start with a question", body: "Pick a place or a theme and see where it takes you.", button: "Start watching" },
};

export type HomeCopy = typeof EN;

const COPY: Record<HomeLocale, HomeCopy> = {
  en: EN,
  fr: {
    hero: {
      badge: "Culturix World",
      title: "Le monde expliqué en courtes vidéos",
      titleAccent: "avec le sens de l'humour",
      body: "Une encyclopédie vidéo du monde créée par l'IA : lieux, phénomènes naturels, espèces et technologie. Chaque vidéo est courte et fondée sur de vraies sources que vous pouvez consulter.",
      ctaPrimary: "Commencer à regarder",
      ctaSecondary: "Comment ça marche",
      note: "Gratuit. Aucun compte nécessaire.",
      latest: "Dernière vidéo",
    },
    stats: { videos: "vidéos publiées", countries: "pays avec des vidéos", themes: "thèmes à explorer", free: "Gratuit", freeLabel: "sans compte" },
    latest: { title: "Tout juste arrivé du monde entier", body: "Les vidéos les plus récentes de l'encyclopédie.", seeAll: "Voir toutes les vidéos" },
    themes: {
      title: "Choisissez un thème",
      body: "Ou suivez un lieu : chaque pays qui a des vidéos a sa propre page, avec des repères et ce dont on y parle aujourd'hui.",
      byPlace: "Explorer par lieu",
      items: {
        place: { name: "Lieux", desc: "Villes, monuments et sites du patrimoine mondial" },
        phenomenon: { name: "Phénomènes", desc: "Merveilles naturelles et événements étranges" },
        species: { name: "Espèces", desc: "Animaux et plantes à découvrir" },
        tech: { name: "Technologie", desc: "Inventions et ce qu'elles ont changé" },
        genz: { name: "Gen Z", desc: "La culture internet, expliquée" },
        custom: { name: "Plus", desc: "Tout ce qui ne rentre dans aucune case" },
      },
    },
    how: {
      eyebrow: "Comment ça marche",
      title: "De vraies sources, de courtes vidéos",
      body: "Beaucoup de vidéos IA sont inventées. Les nôtres partent d'une vraie source et le montrent.",
      steps: [
        { title: "Tout part d'une vraie source", desc: "Chaque vidéo commence par un article Wikipédia ou une fiche du patrimoine mondial de l'UNESCO. Rien n'est inventé." },
        { title: "L'IA écrit, puis se vérifie", desc: "Le script est écrit uniquement à partir de cette source. Une seconde passe signale toute affirmation non étayée, qui est alors réécrite." },
        { title: "Une personne la relit", desc: "Les nouvelles vidéos passent un contrôle qualité et une relecture humaine avant publication, avec un lien vers la source." },
      ],
      sourcesLabel: "Sources",
    },
    trust: {
      eyebrow: "Vérifié, pas deviné",
      title: "Des vidéos courtes, sans faits inventés",
      body: "Beaucoup de gens découvrent le monde par de courtes vidéos, et trop d'entre elles se trompent avec assurance. Culturix garde une trace des sources pour que vous puissiez vérifier.",
      points: [
        "Les vidéos renvoient à la source dont elles sont tirées",
        "Les scripts sont vérifiés par rapport à cette source",
        "Les nouvelles vidéos sont relues par une personne avant publication",
        "Lisez la transcription dans votre langue",
      ],
    },
    faq: {
      title: "Questions",
      items: [
        { q: "Culturix est-il gratuit ?", a: "Oui. Regarder est gratuit et aucun compte n'est nécessaire." },
        { q: "Qui fait les vidéos ?", a: "Elles sont générées par IA à partir d'une vraie source et vérifiées par rapport à elle. Les nouvelles vidéos sont aussi relues par une personne avant publication." },
        { q: "Sont-elles fiables ?", a: "Chaque script est vérifié par rapport à sa source, et les vidéos renvoient à cette source pour que vous puissiez vérifier vous-même." },
        { q: "Pourquoi l'humour ?", a: "On retient mieux ce qui amuse. Le ton est léger ; les faits viennent de la source." },
        { q: "Puis-je regarder dans ma langue ?", a: "Le site existe en anglais, français, allemand et espagnol, et la transcription de chaque vidéo peut être traduite dans d'autres langues." },
      ],
    },
    cta: { title: "Partez d'une question", body: "Choisissez un lieu ou un thème et voyez où cela vous mène.", button: "Commencer à regarder" },
  },
  de: {
    hero: {
      badge: "Culturix World",
      title: "Die Welt in kurzen Videos erklärt",
      titleAccent: "mit Sinn für Humor",
      body: "Eine KI-gemachte Videoenzyklopädie über Orte, Naturphänomene, Arten und Technik. Jedes Video ist kurz und beruht auf echten Quellen, die du nachprüfen kannst.",
      ctaPrimary: "Jetzt ansehen",
      ctaSecondary: "So funktioniert es",
      note: "Kostenlos. Kein Konto nötig.",
      latest: "Neuestes Video",
    },
    stats: { videos: "veröffentlichte Videos", countries: "Länder mit Videos", themes: "Themen zum Entdecken", free: "Kostenlos", freeLabel: "ohne Konto" },
    latest: { title: "Frisch aus aller Welt", body: "Die neuesten Videos der Enzyklopädie.", seeAll: "Alle Videos ansehen" },
    themes: {
      title: "Wähle ein Thema",
      body: "Oder folge einem Ort: Jedes Land mit Videos hat eine eigene Seite mit kurzen Fakten und dem, worüber dort heute gesprochen wird.",
      byPlace: "Nach Ort entdecken",
      items: {
        place: { name: "Orte", desc: "Städte, Wahrzeichen und Welterbestätten" },
        phenomenon: { name: "Phänomene", desc: "Naturwunder und seltsame Ereignisse" },
        species: { name: "Arten", desc: "Tiere und Pflanzen, die man kennen sollte" },
        tech: { name: "Technologie", desc: "Erfindungen und was sie verändert haben" },
        genz: { name: "Gen Z", desc: "Internetkultur, erklärt" },
        custom: { name: "Mehr", desc: "Alles, was in keine Schublade passt" },
      },
    },
    how: {
      eyebrow: "So funktioniert es",
      title: "Echte Quellen rein, kurze Videos raus",
      body: "Viele KI-Videos sind erfunden. Unsere beginnen bei einer echten Quelle und zeigen sie.",
      steps: [
        { title: "Am Anfang steht eine echte Quelle", desc: "Jedes Video beginnt mit einem Wikipedia-Artikel oder einem Eintrag im UNESCO-Welterbe. Nichts wird frei erfunden." },
        { title: "Die KI schreibt und prüft sich selbst", desc: "Das Skript entsteht nur aus dieser Quelle. Ein zweiter Durchgang markiert jede Aussage, die die Quelle nicht stützt, und sie wird neu geschrieben." },
        { title: "Ein Mensch prüft es", desc: "Neue Videos durchlaufen eine Qualitätsprüfung und eine menschliche Prüfung, bevor sie mit einem Link zur Quelle erscheinen." },
      ],
      sourcesLabel: "Quellen",
    },
    trust: {
      eyebrow: "Geprüft, nicht geraten",
      title: "Kurze Videos ohne erfundene Fakten",
      body: "Viele Menschen lernen die Welt heute über kurze Videos kennen, und zu viele davon liegen selbstbewusst falsch. Culturix dokumentiert die Quellen, damit du selbst nachprüfen kannst.",
      points: [
        "Videos verlinken die Quelle, aus der sie entstanden sind",
        "Skripte werden an dieser Quelle geprüft",
        "Neue Videos werden vor der Veröffentlichung von einem Menschen geprüft",
        "Lies das Transkript in deiner Sprache",
      ],
    },
    faq: {
      title: "Fragen",
      items: [
        { q: "Ist Culturix kostenlos?", a: "Ja. Ansehen ist kostenlos, und du brauchst kein Konto." },
        { q: "Wer macht die Videos?", a: "Sie werden mit KI aus einer echten Quelle erstellt und daran geprüft. Neue Videos prüft zusätzlich ein Mensch, bevor sie erscheinen." },
        { q: "Wie genau sind sie?", a: "Jedes Skript wird an seiner Quelle geprüft, und Videos verlinken diese Quelle, damit du selbst nachprüfen kannst." },
        { q: "Warum der Humor?", a: "Was Spaß macht, bleibt besser hängen. Der Ton ist leicht, die Fakten stammen aus der Quelle." },
        { q: "Kann ich in meiner Sprache schauen?", a: "Die Seite gibt es auf Englisch, Französisch, Deutsch und Spanisch, und das Transkript jedes Videos lässt sich in weitere Sprachen übersetzen." },
      ],
    },
    cta: { title: "Fang mit einer Frage an", body: "Wähle einen Ort oder ein Thema und schau, wohin es dich führt.", button: "Jetzt ansehen" },
  },
  es: {
    hero: {
      badge: "Culturix World",
      title: "El mundo explicado en vídeos cortos",
      titleAccent: "con sentido del humor",
      body: "Una enciclopedia en vídeo hecha con IA sobre lugares, fenómenos naturales, especies y tecnología. Cada vídeo es corto y se basa en fuentes reales que puedes comprobar.",
      ctaPrimary: "Empezar a ver",
      ctaSecondary: "Cómo funciona",
      note: "Gratis. Sin necesidad de cuenta.",
      latest: "Último vídeo",
    },
    stats: { videos: "vídeos publicados", countries: "países con vídeos", themes: "temas para explorar", free: "Gratis", freeLabel: "sin cuenta" },
    latest: { title: "Recién llegados de todo el mundo", body: "Los vídeos más nuevos de la enciclopedia.", seeAll: "Ver todos los vídeos" },
    themes: {
      title: "Elige un tema",
      body: "O sigue un lugar: cada país con vídeos tiene su propia página con datos rápidos y de qué se habla allí hoy.",
      byPlace: "Explorar por lugar",
      items: {
        place: { name: "Lugares", desc: "Ciudades, monumentos y Patrimonio Mundial" },
        phenomenon: { name: "Fenómenos", desc: "Maravillas naturales y sucesos extraños" },
        species: { name: "Especies", desc: "Animales y plantas que vale la pena conocer" },
        tech: { name: "Tecnología", desc: "Inventos y lo que cambiaron" },
        genz: { name: "Gen Z", desc: "La cultura de internet, explicada" },
        custom: { name: "Más", desc: "Todo lo que no cabe en una categoría" },
      },
    },
    how: {
      eyebrow: "Cómo funciona",
      title: "Fuentes reales, vídeos cortos",
      body: "Mucho vídeo con IA es inventado. El nuestro parte de una fuente real y la muestra.",
      steps: [
        { title: "Empieza con una fuente real", desc: "Cada vídeo parte de un artículo de Wikipedia o de una ficha del Patrimonio Mundial de la UNESCO. Nada se inventa." },
        { title: "La IA lo escribe y se revisa", desc: "El guion se escribe solo a partir de esa fuente. Una segunda pasada marca cualquier afirmación que la fuente no respalde, y se reescribe." },
        { title: "Una persona lo revisa", desc: "Los vídeos nuevos pasan un control de calidad y una revisión humana antes de publicarse, con un enlace a la fuente." },
      ],
      sourcesLabel: "Fuentes",
    },
    trust: {
      eyebrow: "Comprobado, no supuesto",
      title: "Vídeos cortos, sin datos inventados",
      body: "Mucha gente aprende sobre el mundo con vídeos cortos, y demasiados se equivocan con total seguridad. Culturix guarda las fuentes para que puedas comprobarlo tú.",
      points: [
        "Los vídeos enlazan a la fuente de la que salen",
        "Los guiones se comprueban con esa fuente",
        "Una persona revisa los vídeos nuevos antes de publicarlos",
        "Lee la transcripción en tu idioma",
      ],
    },
    faq: {
      title: "Preguntas",
      items: [
        { q: "¿Culturix es gratis?", a: "Sí. Ver los vídeos es gratis y no necesitas cuenta." },
        { q: "¿Quién hace los vídeos?", a: "Se generan con IA a partir de una fuente real y se comprueban con ella. Además, una persona revisa los vídeos nuevos antes de publicarlos." },
        { q: "¿Son precisos?", a: "Cada guion se comprueba con su fuente, y los vídeos enlazan a esa fuente para que puedas verificarlo tú." },
        { q: "¿Por qué el humor?", a: "Lo que divierte se recuerda mejor. El tono es ligero; los datos vienen de la fuente." },
        { q: "¿Puedo verlo en mi idioma?", a: "El sitio está en inglés, francés, alemán y español, y la transcripción de cada vídeo se puede traducir a más idiomas." },
      ],
    },
    cta: { title: "Empieza con una pregunta", body: "Elige un lugar o un tema y mira adónde te lleva.", button: "Empezar a ver" },
  },
};

export function homeLocale(value: string | null | undefined): HomeLocale {
  return value === "fr" || value === "de" || value === "es" ? value : "en";
}

export function homeCopy(locale: HomeLocale): HomeCopy {
  return COPY[locale];
}
