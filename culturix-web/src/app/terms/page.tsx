import Link from "next/link";
import { Zap } from "lucide-react";

export const metadata = {
  title: "Terms of Service — Culturix",
};

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="mb-8">
      <h2 className="text-lg font-semibold text-gray-900 mb-3">{title}</h2>
      <div className="space-y-3 text-sm text-gray-600 leading-relaxed">{children}</div>
    </section>
  );
}

export default function TermsOfServicePage() {
  const updated = "July 19, 2026";

  return (
    <div className="min-h-screen bg-gray-50">
      <header className="bg-white border-b border-gray-100 sticky top-0 z-10">
        <div className="max-w-3xl mx-auto px-4 sm:px-6 h-16 flex items-center justify-between">
          <Link href="/" className="flex items-center gap-2">
            <Zap className="h-5 w-5 text-blue-600" />
            <span className="font-bold text-lg tracking-tight">Culturix</span>
          </Link>
          <Link href="/privacy" className="text-sm text-gray-500 hover:text-gray-700">
            Privacy Policy
          </Link>
        </div>
      </header>

      <main className="max-w-3xl mx-auto px-4 sm:px-6 py-10">
        <h1 className="text-2xl font-bold text-gray-900 mb-1">Terms of Service</h1>
        <p className="text-xs text-gray-400 mb-8">Last updated: {updated}</p>

        <p className="text-sm text-gray-600 leading-relaxed mb-8">
          These Terms govern your use of Culturix (the &quot;Service&quot;). By creating an account
          or using Culturix, you agree to these Terms.
        </p>

        <Section title="1. The Service">
          <p>Culturix collects public social and cultural trend data, analyzes it, and generates personalized content ideas and AI-assisted media (voiceover, music, video) for your configured audience profiles.</p>
        </Section>

        <Section title="2. Accounts">
          <p>You must provide accurate information when creating an account and are responsible for maintaining the security of your credentials. New accounts require admin approval before full access is granted.</p>
        </Section>

        <Section title="3. Plans &amp; billing">
          <p>Culturix offers a free plan and a paid Pro plan. Pro subscriptions are billed on a recurring basis via Stripe and can be cancelled at any time through the billing portal in Settings — your plan remains active until the end of the current billing period.</p>
        </Section>

        <Section title="4. AI-generated content">
          <p>Content ideas, media (voiceover, music, video), and trend analysis produced by Culturix are generated using third-party AI models. This output may be inaccurate, incomplete, or unsuitable for your purposes. You are solely responsible for reviewing and editing any AI-generated content before publishing it, and for ensuring your use of it complies with the terms of any platform you post it to and applicable law (including intellectual property and platform-impersonation rules).</p>
        </Section>

        <Section title="5. Acceptable use">
          <p>You agree not to: use Culturix for unlawful purposes; attempt to reverse-engineer, scrape, or overload the Service; impersonate another person or entity; or use generated content to mislead audiences about its AI-generated origin where required by applicable law or platform policy.</p>
        </Section>

        <Section title="6. Intellectual property">
          <p>You retain ownership of the content profiles and inputs you provide. Subject to your compliance with these Terms, you may use the content ideas and media Culturix generates for your own commercial or personal purposes.</p>
        </Section>

        <Section title="7. Disclaimers &amp; limitation of liability">
          <p>The Service is provided &quot;as is&quot; without warranties of any kind. Culturix is not liable for any indirect, incidental, or consequential damages arising from your use of the Service, including reliance on trend analysis or AI-generated content.</p>
        </Section>

        <Section title="8. Termination">
          <p>We may suspend or terminate accounts that violate these Terms. You may stop using the Service and request account deletion at any time.</p>
        </Section>

        <Section title="9. Changes to these Terms">
          <p>We may update these Terms from time to time. Continued use of Culturix after changes take effect constitutes acceptance of the revised Terms.</p>
        </Section>

        <Section title="10. Contact">
          <p>Questions about these Terms? Contact us at{" "}
            <a href="mailto:umer.ali79@gmail.com" className="text-blue-600 hover:underline">umer.ali79@gmail.com</a>.
          </p>
        </Section>

        <p className="text-xs text-gray-400 mt-10 border-t border-gray-100 pt-6">
          This is a general-purpose terms template and does not constitute legal advice.
          Consult a qualified lawyer before relying on it for legal or regulatory compliance.
        </p>
      </main>
    </div>
  );
}
