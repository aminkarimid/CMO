# Performance Optimization for X3P Content Manager

## Quick Fixes Applied:

1. **Fixed Tool Validation**: Added default empty lists for `exclude_domains` and `include_domains` to prevent validation errors
2. **Restarted Application**: Fresh app instance running on http://localhost:8502
3. **Simplified Task Complexity**: Consider reducing the number of tools called per task

## Recommended Performance Settings:

### For Faster Execution:
- Limit tool calls per task to maximum 3-5
- Use more specific search queries to get better results faster  
- Consider running simpler crews (e.g., just blog_crew) instead of complex topic_scout
- Use shorter content briefs
- Set max_results to lower values (3-5 instead of 10)
- Control concurrency via env var `X3P_MAX_WORKERS` (default 4)
- Choose pipeline mode: `Optimized` vs `Classic`
  - UI sidebar: "Pipeline mode"
  - Or env var `X3P_PIPELINE_MODE=Optimized|Classic`

### Optimized vs Classic
- Optimized (default): Research → Scholar → SEO Early → Blog, then parallel Channels/Creative, then QA + Care Compliance. Pre‑QA gating may trigger a one‑time blog re‑edit if MAJOR/CRITICAL issues detected.
- Classic: Blog first, then run Channels, QA, and Research/Scholar in parallel. Simpler, lower memory profile.

### Current Issues Causing Slowness:
1. **Over-researching**: Agent is making 20+ tool calls for one task
2. **Complex task requirements**: Topic scout asks for too many different tool types
3. **Network timeouts**: API connection issues causing retries
4. **Validation errors**: Tools failing and requiring retry loops

## Suggested Workflow:
Instead of running the complex topic_scout_task, try simpler crews:
- `blog_crew` - Faster, focused content creation
- `social_crew` - Quick social media posts  
- `research_crew` - Targeted research only

## Performance Monitoring:
- Check terminal output for excessive "🔧 Using" messages
- Look for "🔧 Failed" messages indicating retries
- Monitor for "Connection reset by peer" errors
