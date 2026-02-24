-- Rigovo Teams — Seed System Team Templates

insert into team_templates (name, description, agents, is_system) values
  ('full-stack', 'Complete feature development: plan, code, review', array['planner', 'coder', 'reviewer'], true),
  ('quick-fix', 'Fast bug fix or patch: code and review', array['coder', 'reviewer'], true),
  ('code-review', 'Review-only workflow for existing code', array['reviewer'], true),
  ('incident-response', 'Production incident handling: SRE lead with coder support', array['sre', 'coder'], true),
  ('infrastructure', 'Infrastructure and deployment changes', array['devops', 'sre'], true),
  ('test-suite', 'Test generation and validation', array['qa', 'coder'], true);
