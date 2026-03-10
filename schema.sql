-- =====================================================
-- Content AI Generator — Supabase Database Schema
-- Run this in: Supabase Dashboard → SQL Editor → New query
-- =====================================================

-- Enable UUID extension (usually already enabled)
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- =====================================================
-- 1. PROFILES (extends auth.users)
-- =====================================================
CREATE TABLE IF NOT EXISTS public.profiles (
    id UUID PRIMARY KEY REFERENCES auth.users(id) ON DELETE CASCADE,
    email TEXT,
    full_name TEXT,
    avatar_url TEXT,
    plan TEXT NOT NULL DEFAULT 'free' CHECK (plan IN ('free', 'pro', 'business')),
    stripe_customer_id TEXT UNIQUE,
    openrouter_api_key_enc TEXT,
    serper_api_key_enc TEXT,
    fal_key_enc TEXT,
    ntfy_topic TEXT,
    beehiiv_pub_id TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- =====================================================
-- 2. SUBSCRIPTIONS (Stripe integration)
-- =====================================================
CREATE TABLE IF NOT EXISTS public.subscriptions (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID NOT NULL UNIQUE REFERENCES auth.users(id) ON DELETE CASCADE,
    stripe_subscription_id TEXT UNIQUE,
    stripe_price_id TEXT,
    plan TEXT NOT NULL DEFAULT 'free' CHECK (plan IN ('free', 'pro', 'business')),
    status TEXT NOT NULL DEFAULT 'active'
        CHECK (status IN ('active', 'canceled', 'past_due', 'trialing', 'incomplete')),
    current_period_start TIMESTAMPTZ,
    current_period_end TIMESTAMPTZ,
    cancel_at_period_end BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- =====================================================
-- 3. ARTICLES (scored RSS / search / custom articles)
-- =====================================================
CREATE TABLE IF NOT EXISTS public.articles (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    url TEXT,
    title TEXT,
    description TEXT,
    source TEXT,
    feed_category TEXT,
    published TIMESTAMPTZ,
    category TEXT,
    score INTEGER DEFAULT 5,
    summary TEXT,
    scored_at TIMESTAMPTZ,
    base_score INTEGER,
    boost NUMERIC(4,2),
    source_mode TEXT DEFAULT 'rss',
    link TEXT,
    score_reason TEXT,
    custom_text TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- =====================================================
-- 4. SESSIONS (content generation sessions)
-- =====================================================
CREATE TABLE IF NOT EXISTS public.sessions (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    article JSONB DEFAULT '{}'::jsonb,
    topics JSONB DEFAULT '[]'::jsonb,
    opinion TEXT DEFAULT '',
    content JSONB DEFAULT '{}'::jsonb,
    carousel_images JSONB DEFAULT '{}'::jsonb,
    platforms JSONB DEFAULT '[]'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- =====================================================
-- 5. SCHEDULES (content publishing schedule)
-- =====================================================
CREATE TABLE IF NOT EXISTS public.schedules (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    platform TEXT,
    title TEXT,
    content_preview TEXT,
    content_key TEXT,
    session_id UUID,
    scheduled_at TIMESTAMPTZ,
    status TEXT DEFAULT 'pending'
        CHECK (status IN ('pending', 'notified', 'published')),
    notified_at TIMESTAMPTZ,
    published_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- =====================================================
-- 6. FEEDBACK (per-format feedback entries)
-- =====================================================
CREATE TABLE IF NOT EXISTS public.feedback (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    format_type TEXT NOT NULL,
    feedback TEXT NOT NULL,
    enriched_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- =====================================================
-- 7. FEEDS CONFIG (RSS feed categories per user)
-- =====================================================
CREATE TABLE IF NOT EXISTS public.feeds_config (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID NOT NULL UNIQUE REFERENCES auth.users(id) ON DELETE CASCADE,
    categories JSONB NOT NULL DEFAULT '{}'::jsonb,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- =====================================================
-- 8. PIPELINE LOGS (operational logs)
-- =====================================================
CREATE TABLE IF NOT EXISTS public.pipeline_logs (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    level TEXT NOT NULL,
    message TEXT NOT NULL,
    extra JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- =====================================================
-- 9. PROMPT LOGS (prompt version history)
-- =====================================================
CREATE TABLE IF NOT EXISTS public.prompt_logs (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    prompt_name TEXT NOT NULL,
    version INTEGER NOT NULL DEFAULT 1,
    content TEXT NOT NULL,
    trigger TEXT DEFAULT 'init',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- =====================================================
-- 10. SELECTION PREFERENCES (learning engine)
-- =====================================================
CREATE TABLE IF NOT EXISTS public.selection_prefs (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID NOT NULL UNIQUE REFERENCES auth.users(id) ON DELETE CASCADE,
    source_counts JSONB NOT NULL DEFAULT '{}'::jsonb,
    category_counts JSONB NOT NULL DEFAULT '{}'::jsonb,
    keyword_counts JSONB NOT NULL DEFAULT '{}'::jsonb,
    total_selections INTEGER NOT NULL DEFAULT 0,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- =====================================================
-- 11. WEEKLY STATUS (content tracking per week)
-- =====================================================
CREATE TABLE IF NOT EXISTS public.weekly_status (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    week_key TEXT NOT NULL,
    platform TEXT NOT NULL,
    generated INTEGER NOT NULL DEFAULT 0,
    approved INTEGER NOT NULL DEFAULT 0,
    scheduled INTEGER NOT NULL DEFAULT 0,
    published INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(user_id, week_key, platform)
);

-- =====================================================
-- INDEXES
-- =====================================================
CREATE INDEX IF NOT EXISTS idx_articles_user ON articles(user_id);
CREATE INDEX IF NOT EXISTS idx_articles_user_score ON articles(user_id, score DESC);
CREATE INDEX IF NOT EXISTS idx_sessions_user ON sessions(user_id);
CREATE INDEX IF NOT EXISTS idx_sessions_user_created ON sessions(user_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_schedules_user ON schedules(user_id);
CREATE INDEX IF NOT EXISTS idx_schedules_user_status ON schedules(user_id, status);
CREATE INDEX IF NOT EXISTS idx_schedules_pending ON schedules(status) WHERE status = 'pending';
CREATE INDEX IF NOT EXISTS idx_feedback_user_format ON feedback(user_id, format_type);
CREATE INDEX IF NOT EXISTS idx_pipeline_logs_user_created ON pipeline_logs(user_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_prompt_logs_user_name ON prompt_logs(user_id, prompt_name);
CREATE INDEX IF NOT EXISTS idx_weekly_status_user_week ON weekly_status(user_id, week_key);

-- =====================================================
-- ROW LEVEL SECURITY (RLS)
-- =====================================================
ALTER TABLE profiles ENABLE ROW LEVEL SECURITY;
ALTER TABLE subscriptions ENABLE ROW LEVEL SECURITY;
ALTER TABLE articles ENABLE ROW LEVEL SECURITY;
ALTER TABLE sessions ENABLE ROW LEVEL SECURITY;
ALTER TABLE schedules ENABLE ROW LEVEL SECURITY;
ALTER TABLE feedback ENABLE ROW LEVEL SECURITY;
ALTER TABLE feeds_config ENABLE ROW LEVEL SECURITY;
ALTER TABLE pipeline_logs ENABLE ROW LEVEL SECURITY;
ALTER TABLE prompt_logs ENABLE ROW LEVEL SECURITY;
ALTER TABLE selection_prefs ENABLE ROW LEVEL SECURITY;
ALTER TABLE weekly_status ENABLE ROW LEVEL SECURITY;

-- Profiles
CREATE POLICY "profiles_select" ON profiles FOR SELECT USING (auth.uid() = id);
CREATE POLICY "profiles_insert" ON profiles FOR INSERT WITH CHECK (auth.uid() = id);
CREATE POLICY "profiles_update" ON profiles FOR UPDATE USING (auth.uid() = id);

-- Subscriptions (read-only for users; server manages via service_role)
CREATE POLICY "subscriptions_select" ON subscriptions FOR SELECT USING (auth.uid() = user_id);

-- Articles
CREATE POLICY "articles_all" ON articles FOR ALL USING (auth.uid() = user_id) WITH CHECK (auth.uid() = user_id);

-- Sessions
CREATE POLICY "sessions_all" ON sessions FOR ALL USING (auth.uid() = user_id) WITH CHECK (auth.uid() = user_id);

-- Schedules
CREATE POLICY "schedules_all" ON schedules FOR ALL USING (auth.uid() = user_id) WITH CHECK (auth.uid() = user_id);

-- Feedback
CREATE POLICY "feedback_all" ON feedback FOR ALL USING (auth.uid() = user_id) WITH CHECK (auth.uid() = user_id);

-- Feeds Config
CREATE POLICY "feeds_config_all" ON feeds_config FOR ALL USING (auth.uid() = user_id) WITH CHECK (auth.uid() = user_id);

-- Pipeline Logs
CREATE POLICY "pipeline_logs_select" ON pipeline_logs FOR SELECT USING (auth.uid() = user_id);
CREATE POLICY "pipeline_logs_insert" ON pipeline_logs FOR INSERT WITH CHECK (auth.uid() = user_id);

-- Prompt Logs
CREATE POLICY "prompt_logs_select" ON prompt_logs FOR SELECT USING (auth.uid() = user_id);
CREATE POLICY "prompt_logs_insert" ON prompt_logs FOR INSERT WITH CHECK (auth.uid() = user_id);

-- Selection Prefs
CREATE POLICY "selection_prefs_all" ON selection_prefs FOR ALL USING (auth.uid() = user_id) WITH CHECK (auth.uid() = user_id);

-- Weekly Status
CREATE POLICY "weekly_status_all" ON weekly_status FOR ALL USING (auth.uid() = user_id) WITH CHECK (auth.uid() = user_id);

-- =====================================================
-- HELPER FUNCTION: Increment weekly status counter
-- =====================================================
CREATE OR REPLACE FUNCTION public.increment_weekly_status(
    p_user_id UUID,
    p_week_key TEXT,
    p_platform TEXT,
    p_action TEXT
) RETURNS VOID AS $$
BEGIN
    -- Insert row if not exists
    INSERT INTO weekly_status (user_id, week_key, platform)
    VALUES (p_user_id, p_week_key, p_platform)
    ON CONFLICT (user_id, week_key, platform) DO NOTHING;

    -- Increment the specified counter
    EXECUTE format(
        'UPDATE weekly_status SET %I = %I + 1 WHERE user_id = $1 AND week_key = $2 AND platform = $3',
        p_action, p_action
    ) USING p_user_id, p_week_key, p_platform;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

-- =====================================================
-- TRIGGER: Auto-create profile + defaults on signup
-- =====================================================
CREATE OR REPLACE FUNCTION public.handle_new_user()
RETURNS TRIGGER AS $$
BEGIN
    INSERT INTO public.profiles (id, email, full_name)
    VALUES (
        NEW.id,
        NEW.email,
        COALESCE(NEW.raw_user_meta_data->>'full_name', '')
    );
    INSERT INTO public.subscriptions (user_id, plan, status)
    VALUES (NEW.id, 'free', 'active');
    INSERT INTO public.feeds_config (user_id, categories)
    VALUES (NEW.id, '{}'::jsonb);
    INSERT INTO public.selection_prefs (user_id)
    VALUES (NEW.id);
    RETURN NEW;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

-- Drop trigger if exists to allow re-running
DROP TRIGGER IF EXISTS on_auth_user_created ON auth.users;
CREATE TRIGGER on_auth_user_created
    AFTER INSERT ON auth.users
    FOR EACH ROW EXECUTE FUNCTION public.handle_new_user();
