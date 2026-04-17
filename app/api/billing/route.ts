import { NextResponse } from 'next/server';
import { auth } from '@clerk/nextjs/server';

export async function GET() {
  const { userId } = await auth();
  if (!userId) {
    return new NextResponse('Unauthorized', { status: 401 });
  }

  // SPEC v1.3.0 Section 8: Pricing & Overage
  return NextResponse.json({
    plan: "Standard",
    price: "$9.00/mo",
    overage: {
      hot: "€6.00 / GB / month",
      cold: "€3.00 / GB / month"
    },
    stripePortalUrl: "https://billing.stripe.com/p/session/test_...",
    contactSales: "drizzo.ai@gmail.com"
  });
}
