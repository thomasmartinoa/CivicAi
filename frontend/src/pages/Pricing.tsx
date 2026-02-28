import { Link } from 'react-router-dom';

const PLANS = [
  {
    name: 'Free',
    price: '₹0',
    period: '/month',
    tag: null,
    description: 'Perfect for small panchayats getting started.',
    limit: '50 complaints/month',
    features: [
      'AI complaint classification',
      'Basic work order creation',
      'Email notifications',
      'Public dashboard',
      'Citizen tracking',
    ],
    cta: 'Get started free',
    ctaLink: '/submit',
    highlight: false,
  },
  {
    name: 'Pro',
    price: '₹2,999',
    period: '/month',
    tag: 'Most popular',
    description: 'For growing municipalities managing hundreds of issues.',
    limit: 'Unlimited complaints',
    features: [
      'Everything in Free',
      'Auto-contractor assignment',
      'SLA breach auto-escalation',
      'Cluster detection agent',
      'Daily officer AI briefing',
      'Citizen satisfaction scoring',
      'Analytics & performance reports',
      'Priority email support',
    ],
    cta: 'Start Pro trial',
    ctaLink: '/admin/login',
    highlight: true,
  },
  {
    name: 'Enterprise',
    price: 'Custom',
    period: '',
    tag: null,
    description: 'For district councils, corporations, and large deployments.',
    limit: 'Unlimited + multi-tenant',
    features: [
      'Everything in Pro',
      'Multi-ward / multi-district tenancy',
      'Custom AI agent configuration',
      'Dedicated SLA SLAs',
      'On-premise deployment option',
      'API access & webhooks',
      'Custom branding',
      'Dedicated support manager',
    ],
    cta: 'Contact sales',
    ctaLink: 'mailto:sales@civicai.gov',
    highlight: false,
  },
];

const CONTRACTOR_PLANS = [
  {
    name: 'Basic Listing',
    price: '₹499',
    period: '/month',
    features: ['Profile on contractor marketplace', 'Manual job applications', 'Basic support'],
  },
  {
    name: 'Verified Contractor',
    price: '2% per job',
    period: 'commission',
    features: ['AI auto-assignment priority', 'Performance rating badge', 'SMS job alerts', 'Zero monthly fee'],
  },
];

export default function Pricing() {
  return (
    <div className="min-h-screen bg-gray-50">
      {/* Navbar */}
      <nav className="bg-blue-900 text-white shadow-lg">
        <div className="max-w-7xl mx-auto px-4 py-3 flex items-center justify-between">
          <Link to="/" className="text-xl font-bold">CivicAI</Link>
          <div className="flex gap-4 text-sm">
            <Link to="/submit" className="hover:text-blue-200">Submit</Link>
            <Link to="/track" className="hover:text-blue-200">Track</Link>
            <Link to="/dashboard" className="hover:text-blue-200">Dashboard</Link>
            <Link to="/admin/login" className="px-3 py-1 bg-white text-blue-900 rounded font-medium hover:bg-blue-50">Admin</Link>
          </div>
        </div>
      </nav>

      <main className="max-w-6xl mx-auto px-4 py-16">
        {/* Header */}
        <div className="text-center mb-14">
          <h1 className="text-4xl font-bold text-blue-900">Simple, transparent pricing</h1>
          <p className="mt-3 text-gray-500 text-lg max-w-2xl mx-auto">
            CivicAI pays for itself — one prevented SLA breach saves more than a year of Pro subscription.
          </p>
        </div>

        {/* Municipality Plans */}
        <h2 className="text-xl font-semibold text-blue-900 mb-6">For municipalities & panchayats</h2>
        <div className="grid grid-cols-1 md:grid-cols-3 gap-6 mb-16">
          {PLANS.map((plan) => (
            <div
              key={plan.name}
              className={`relative rounded-2xl p-7 shadow border flex flex-col ${
                plan.highlight
                  ? 'bg-blue-900 text-white border-blue-900 scale-105 shadow-xl'
                  : 'bg-white text-gray-800 border-gray-200'
              }`}
            >
              {plan.tag && (
                <span className="absolute -top-3 left-6 bg-yellow-400 text-blue-900 text-xs font-bold px-3 py-1 rounded-full">
                  {plan.tag}
                </span>
              )}
              <div>
                <div className={`text-sm font-medium uppercase tracking-wide ${plan.highlight ? 'text-blue-200' : 'text-gray-500'}`}>
                  {plan.name}
                </div>
                <div className="mt-2 flex items-baseline gap-1">
                  <span className="text-4xl font-bold">{plan.price}</span>
                  <span className={`text-sm ${plan.highlight ? 'text-blue-200' : 'text-gray-400'}`}>{plan.period}</span>
                </div>
                <p className={`mt-2 text-sm ${plan.highlight ? 'text-blue-100' : 'text-gray-500'}`}>{plan.description}</p>
                <p className={`mt-1 text-xs font-medium ${plan.highlight ? 'text-yellow-300' : 'text-blue-700'}`}>{plan.limit}</p>
              </div>
              <ul className="mt-6 space-y-2 flex-1">
                {plan.features.map((f) => (
                  <li key={f} className="flex items-start gap-2 text-sm">
                    <span className={`mt-0.5 ${plan.highlight ? 'text-green-300' : 'text-green-600'}`}>✓</span>
                    <span className={plan.highlight ? 'text-blue-50' : 'text-gray-700'}>{f}</span>
                  </li>
                ))}
              </ul>
              <div className="mt-8">
                {plan.ctaLink.startsWith('mailto') ? (
                  <a
                    href={plan.ctaLink}
                    className={`block text-center py-3 rounded-xl font-semibold transition ${
                      plan.highlight
                        ? 'bg-white text-blue-900 hover:bg-blue-50'
                        : 'bg-blue-900 text-white hover:bg-blue-800'
                    }`}
                  >
                    {plan.cta}
                  </a>
                ) : (
                  <Link
                    to={plan.ctaLink}
                    className={`block text-center py-3 rounded-xl font-semibold transition ${
                      plan.highlight
                        ? 'bg-white text-blue-900 hover:bg-blue-50'
                        : 'bg-blue-900 text-white hover:bg-blue-800'
                    }`}
                  >
                    {plan.cta}
                  </Link>
                )}
              </div>
            </div>
          ))}
        </div>

        {/* Contractor Plans */}
        <h2 className="text-xl font-semibold text-blue-900 mb-6">For contractors</h2>
        <div className="grid grid-cols-1 md:grid-cols-2 gap-6 mb-16">
          {CONTRACTOR_PLANS.map((plan) => (
            <div key={plan.name} className="bg-white rounded-2xl p-6 shadow border border-gray-200">
              <div className="text-sm font-medium text-gray-500 uppercase tracking-wide">{plan.name}</div>
              <div className="mt-2 flex items-baseline gap-1">
                <span className="text-3xl font-bold text-blue-900">{plan.price}</span>
                <span className="text-sm text-gray-400">{plan.period}</span>
              </div>
              <ul className="mt-4 space-y-2">
                {plan.features.map((f) => (
                  <li key={f} className="flex items-center gap-2 text-sm text-gray-700">
                    <span className="text-green-600">✓</span>{f}
                  </li>
                ))}
              </ul>
              <Link to="/admin/login" className="mt-5 block text-center py-2.5 bg-blue-900 text-white rounded-xl font-medium hover:bg-blue-800 transition text-sm">
                Register as contractor
              </Link>
            </div>
          ))}
        </div>

        {/* Revenue model callout */}
        <div className="bg-blue-900 text-white rounded-2xl p-8 text-center">
          <h3 className="text-2xl font-bold">Built for sustainable civic tech</h3>
          <p className="mt-3 text-blue-100 max-w-2xl mx-auto">
            CivicAI generates revenue through municipal SaaS subscriptions and a contractor marketplace commission.
            Every rupee stays in the local civic ecosystem.
          </p>
          <div className="mt-6 grid grid-cols-3 gap-6 text-center">
            <div>
              <div className="text-3xl font-bold text-yellow-300">₹2,999</div>
              <div className="text-sm text-blue-200 mt-1">Pro plan per municipality/month</div>
            </div>
            <div>
              <div className="text-3xl font-bold text-yellow-300">2%</div>
              <div className="text-sm text-blue-200 mt-1">Commission per assigned job</div>
            </div>
            <div>
              <div className="text-3xl font-bold text-yellow-300">₹49</div>
              <div className="text-sm text-blue-200 mt-1">Citizen premium/month</div>
            </div>
          </div>
        </div>
      </main>
    </div>
  );
}
