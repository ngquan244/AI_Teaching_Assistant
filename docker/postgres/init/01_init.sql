-- PostgreSQL Initialization Script
-- This script runs when the container is first created

-- Enable required extensions
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "pgcrypto";

-- Create function for generating UUIDs (if needed)
-- PostgreSQL 13+ has gen_random_uuid() built-in

-- Set default timezone
SET timezone = 'UTC';

-- Create read-only role for analytics (optional)
-- CREATE ROLE readonly_user WITH LOGIN PASSWORD 'readonly_password';
-- GRANT CONNECT ON DATABASE grader_db TO readonly_user;
-- GRANT USAGE ON SCHEMA public TO readonly_user;
-- GRANT SELECT ON ALL TABLES IN SCHEMA public TO readonly_user;
