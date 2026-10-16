// Public settings for the browser. The publishable key is meant to be public;
// Row Level Security in supabase/schema.sql keeps each player's data private.
window.MNM_CONFIG = {
  supabaseUrl: "https://tdmkwojyhzptdgvsjjmi.supabase.co",
  supabaseAnonKey: "sb_publishable_HU7B86p_zQ1v-A1VlkEoIg_oFz0cntY",
  // Sign-in options shown next to email, enabled in Supabase > Authentication > Providers
  // Add "discord" once it is switched on in Supabase, or its button shows an error.
  providers: [],
  // "Ask the guide" uses the Supabase Edge Function in supabase/functions/ask
  // Set to true once the ask function and its ANTHROPIC_API_KEY secret are in Supabase.
  ask: false,
  // Link for a "Support the site" button (Buy Me a Coffee, Ko-fi, ...). Leave empty to hide it.
  donateUrl: ""
};
