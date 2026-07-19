import Link from "next/link";
import { Zap } from "lucide-react";

export const metadata = {
  title: "Privacy Policy — Culturix",
};

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="mb-8">
      <h2 className="text-lg font-semibold text-gray-900 mb-3">{title}</h2>
      <div className="space-y-3 text-sm text-gray-600 leading-relaxed">{children}</div>
    </section>
  );
}

export default function PrivacyPolicyPage() {
  const updated = "July 19, 2026";

  return (
    <div className="min-h-screen bg-gray-50">
      <header className="bg-white border-b border-gray-100 sticky top-0 z-10">
        <div className="max-w-3xl mx-auto px-4 sm:px-6 h-16 flex items-center justify-between">
          <Link href="/" className="flex items-center gap-2">
            <Zap className="h-5 w-5 text-blue-600" />
            <span className="font-bold text-lg tracking-tight">Culturix</span>
          </Link>
          <Link href="/terms" className="text-sm text-gray-500 hover:text-gray-700">
            Terms of Service
          </Link>
        </div>
      </header>

      <main className="max-w-3xl mx-auto px-4 sm:px-6 py-10">
        <h1 className="text-2xl font-bold text-gray-900 mb-1">Privacy Policy</h1>
        <p className="text-xs text-gray-400 mb-8">Last updated: {updated}</p>

        <p className="text-sm text-gray-600 leading-relaxed mb-8">
          Culturix (&quot;we&quot;, &quot;us&quot;) provides a trend-intelligence and content-generation
          platform. This policy explains what data we collect, how we use it, and the
          third-party services we rely on to operate Culturix.
        </p>

        <Section title="1. Information we collect">
          <p><strong>Account information:</strong> email address and authentication credentials, handled via Supabase Auth.</p>
          <p><strong>Content profile data:</strong> the audience, niche, tone, platform, and region preferences you configure to personalize your trend digests.</p>
          <p><strong>Billing information:</strong> if you upgrade to Pro, payment is processed by Stripe. We do not store your card details — Stripe handles that directly.</p>
          <p><strong>Usage data:</strong> which features you use (e.g. media generation requests), for quota enforcement and service improvement.</p>
          <p><strong>Public trend data:</strong> we separately collect publicly available social media posts and trending topics (from platforms including Twitter/X, YouTube, TikTok, Wikipedia, Bluesky, Pinterest) to power our trend-analysis engine. This is public third-party content, not personal data about Culturix account holders.</p>
        </Section>

        <Section title="2. How we use your information">
          <p>We use your information to: operate and personalize your account, generate trend-based content ideas and media for you, process payments, enforce plan limits, communicate with you about your account (including daily digest emails), and improve Culturix.</p>
        </Section>

        <Section title="3. Third-party services we use">
          <p>Culturix relies on the following third-party providers, each of which may process data as part of delivering the service:</p>
          <ul className="list-disc pl-5 space-y-1">
            <li><strong>Supabase</strong> — authentication and session management</li>
            <li><strong>Railway</strong> — application hosting and database</li>
            <li><strong>Vercel</strong> — frontend hosting</li>
            <li><strong>Stripe</strong> — payment processing</li>
            <li><strong>Anthropic (Claude), Qwen, DeepSeek</strong> — AI models used to analyze trends and generate content ideas</li>
            <li><strong>Voyage AI &amp; Qdrant</strong> — text embeddings and semantic search over trend data</li>
            <li><strong>Microsoft Edge TTS, MiniMax (via aimlapi), Kling</strong> — AI voiceover, music, and video generation, if you use those features</li>
            <li><strong>Apify</strong> — collection of public trend data from third-party platforms</li>
            <li><strong>Resend</strong> — transactional and digest email delivery</li>
          </ul>
          <p>When you use a feature backed by one of these providers (e.g. generating a voiceover), the relevant input (such as a text prompt) is sent to that provider to produce the output.</p>
        </Section>

        <Section title="4. Data retention">
          <p>We retain account and content data for as long as your account is active. You may request deletion of your account and associated data at any time by contacting us (below).</p>
        </Section>

        <Section title="5. Your rights">
          <p>Depending on your location, you may have rights to access, correct, export, or delete your personal data. Contact us to exercise these rights.</p>
        </Section>

        <Section title="6. Children's privacy">
          <p>Culturix is not directed at children under 16, and we do not knowingly collect personal information from them.</p>
        </Section>

        <Section title="7. Changes to this policy">
          <p>We may update this policy from time to time. Material changes will be reflected by updating the &quot;Last updated&quot; date above.</p>
        </Section>

        <Section title="8. Contact">
          <p>Questions about this policy? Contact us at{" "}
            <a href="mailto:umer.ali79@gmail.com" className="text-blue-600 hover:underline">umer.ali79@gmail.com</a>.
          </p>
        </Section>

        <p className="text-xs text-gray-400 mt-10 border-t border-gray-100 pt-6">
          This is a general-purpose policy template and does not constitute legal advice.
          Consult a qualified lawyer to ensure full compliance with applicable law (e.g. GDPR, CCPA)
          for your specific jurisdictions and user base.
        </p>
      </main>
    </div>
  );
}
