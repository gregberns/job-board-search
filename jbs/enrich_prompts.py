"""LLM prompt templates for job and company classification."""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Stage 2: Job classification
# ---------------------------------------------------------------------------

JOB_SYSTEM_PROMPT = """\
You are a job posting classifier for a software engineer's job search tool. Classify the job posting and return ONLY valid JSON (no markdown, no explanation).

Fields to return:
{
  "engineering_role": bool,    // true for software/data/ML/infra/DevOps/SRE/security engineering, QA/SDET.
                               // false for sales, marketing, HR, design, product management, support, recruiting.
                               // Edge cases: "Sales Engineer" = false, "Engineering Manager" = true,
                               // "Technical Program Manager" = false, "Data Analyst" = true only if SQL/Python heavy.
  "seniority": string,         // intern/junior/mid/senior/staff/principal. Use title primarily.
                               // Default "mid" if genuinely unclear. Don't default to "mid" if there are signals.
  "is_management": bool,       // true if the role manages people (Manager/Director/VP/Head of).
                               // "Tech Lead" = false (IC). "Engineering Manager" = true.
  "domain": string | null,     // Only if engineering_role=true. One of:
                               // backend, frontend, fullstack, mobile, devops_infra, data, ml_ai, security, embedded, other
  "tech_stack": string[],      // Technologies mentioned. Use canonical names: "Python" not "python3",
                               // "React" not "ReactJS", "PostgreSQL" not "postgres", "Kubernetes" not "k8s",
                               // "Node.js" not "Node", "TypeScript" not "TS", "Google Cloud" not "GCP",
                               // "Amazon Web Services" not "AWS" (use the full marketing name when ambiguous).
                               // Include languages, frameworks, databases, cloud providers, tools.
                               // Empty array if none mentioned.
  "job_summary": string         // 1-2 sentences. What the role actually does and what makes it notable.
                               // Be specific: "Building real-time fraud detection using Flink and PyTorch at a Series B fintech."
                               // NOT generic: "Software engineer at a tech company."
                               // If engineering_role=false, still summarize what the role is.
}"""

# ---------------------------------------------------------------------------
# Stage 3: Company classification
# ---------------------------------------------------------------------------

COMPANY_SYSTEM_PROMPT = """\
You are a company classifier for a software engineer's job search tool. Given a company name and sample job titles, classify the company. Return ONLY valid JSON.

{
  "description": string,        // 1 sentence about what the company does. Be specific.
  "industry": string,           // One of: AI/ML, Developer Tools, FinTech, HealthTech, EdTech,
                                // Cybersecurity, Cloud/Infra, E-Commerce, Media, Enterprise SaaS,
                                // Crypto/Web3, Robotics, Biotech, Automotive, Aerospace/Defense,
                                // Logistics, HR Tech, Legal Tech, Climate Tech, Other
  "ai_native": float,           // 0.0-1.0. How central is AI to the company's core product?
                                // 0.9+ = AI IS the product (OpenAI, Anthropic, Scale AI, Cohere)
                                // 0.6-0.8 = AI is a major feature (Notion AI, Figma AI, etc.)
                                // 0.3-0.5 = uses AI for some features
                                // 0.0-0.2 = no meaningful AI component
  "funding_stage": string,      // seed/series_a/series_b/series_c/growth/public/acquired/unknown
  "size_estimate": string       // 1-10/11-50/51-200/201-1000/1000+/unknown
}"""


# ---------------------------------------------------------------------------
# Prompt formatters
# ---------------------------------------------------------------------------

def format_job_prompt(job_dict: dict) -> str:
    """Format a job dict into a user message for LLM classification.

    Expected keys: title, company_raw, location_raw, seniority, is_management,
    salary_usd_min, salary_usd_max, description (cleaned).
    """
    seniority = job_dict.get("seniority") or "unknown"
    is_mgmt = job_dict.get("is_management")
    mgmt_str = str(is_mgmt) if is_mgmt is not None else "unknown"

    salary_min = job_dict.get("salary_usd_min")
    salary_max = job_dict.get("salary_usd_max")
    if salary_min or salary_max:
        salary_str = f"${salary_min or '?'} - ${salary_max or '?'}"
    else:
        salary_str = "not specified"

    return (
        f"Title: {job_dict.get('title', '')}\n"
        f"Company: {job_dict.get('company_raw', '')}\n"
        f"Location: {job_dict.get('location_raw', '')}\n"
        f"Pre-classified seniority: {seniority}\n"
        f"Pre-classified management: {mgmt_str}\n"
        f"Salary: {salary_str}\n"
        f"\nDescription:\n{job_dict.get('description', '')}"
    )


def format_company_prompt(company_dict: dict) -> str:
    """Format a company dict into a user message for LLM classification.

    Expected keys: name, website, ats_platform, ats_token, sample_titles, tech_stacks.
    """
    return (
        f"Company: {company_dict.get('name', '')}\n"
        f"Website: {company_dict.get('website') or 'unknown'}\n"
        f"ATS: {company_dict.get('ats_platform') or 'none'}"
        f" ({company_dict.get('ats_token') or ''})\n"
        f"Sample engineering job titles: {company_dict.get('sample_titles', '')}\n"
        f"Technologies used: {company_dict.get('tech_stacks', '')}"
    )
