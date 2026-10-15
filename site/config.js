// Public settings for the browser. The publishable key is meant to be public;
// Row Level Security in supabase/schema.sql keeps each player's data private.
window.MNM_CONFIG = {
  supabaseUrl: "https://tdmkwojyhzptdgvsjjmi.supabase.co",
  supabaseAnonKey: "sb_publishable_HU7B86p_zQ1v-A1VlkEoIg_oFz0cntY",
  // Sign-in options shown next to email, enabled in Supabase > Authentication > Providers
  providers: ["discord"],
  // "Ask the guide" uses the Supabase Edge Function in supabase/functions/ask
  ask: true,
  // Link for a "Support the site" button (Buy Me a Coffee, Ko-fi, ...). Leave empty to hide it.
  donateUrl: ""
};
