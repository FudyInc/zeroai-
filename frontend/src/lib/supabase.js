import { createClient } from '@supabase/supabase-js'

// Claves públicas por diseño (anon/publishable key) — seguras de exponer en
// el frontend, a diferencia de SUPABASE_KEY (service_role) que vive SOLO en
// el backend y nunca debe llegar acá. Proyecto "zeroai".
const SUPABASE_URL = 'https://lhdvybpgyexxypjtthce.supabase.co'
const SUPABASE_ANON_KEY = 'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImxoZHZ5YnBneWV4eHlwanR0aGNlIiwicm9sZSI6ImFub24iLCJpYXQiOjE3ODM2NDI3MjcsImV4cCI6MjA5OTIxODcyN30.DpbxZLS4BwwtpI6ctO_BF0C3e9o4mfMZ3m_8qjar_wA'

export const supabase = createClient(SUPABASE_URL, SUPABASE_ANON_KEY)
