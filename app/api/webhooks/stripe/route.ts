import { NextResponse } from 'next/server';
import Stripe from 'stripe';
import { createClient } from '@supabase/supabase-js';

const stripe = new Stripe(process.env.STRIPE_SECRET_KEY!, {
  apiVersion: '2023-10-16',
});

const webhookSecret = process.env.STRIPE_WEBHOOK_SECRET!;
const supabaseUrl = process.env.NEXT_PUBLIC_SUPABASE_URL!;
const supabaseServiceKey = process.env.SUPABASE_SERVICE_ROLE_KEY!;

const supabaseAdmin = createClient(supabaseUrl, supabaseServiceKey);

export async function POST(req: Request) {
  const body = await req.text();
  const signature = req.headers.get('stripe-signature') as string;

  let event: Stripe.Event;

  try {
    event = stripe.webhooks.constructEvent(body, signature, webhookSecret);
  } catch (err: any) {
    console.error(`Webhook signature verification failed: ${err.message}`);
    return new NextResponse(`Webhook Error: ${err.message}`, { status: 400 });
  }

  // Handle the event
  if (event.type === 'checkout.session.completed' || event.type === 'customer.subscription.updated') {
    const session = event.data.object as any;
    const userId = session.metadata?.user_id; // Passed from client during checkout

    if (userId) {
      const { error } = await supabaseAdmin.from('subscriptions').upsert({
        user_id: userId,
        stripe_subscription_id: session.subscription || session.id,
        status: 'active',
        tier: session.metadata?.tier || 'pro',
        updated_at: new Date().toISOString(),
      }, {
        onConflict: 'user_id'
      });

      if (error) {
        console.error('Supabase upsert error:', error.message);
        return new NextResponse(`Database Error: ${error.message}`, { status: 500 });
      }
    }
  }

  return new NextResponse(JSON.stringify({ received: true }), { status: 200 });
}
