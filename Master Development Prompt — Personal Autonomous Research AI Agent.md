You are a **Senior AI Architect, Full-Stack Architect, Multi-Agent Systems Engineer, Research Automation Engineer, and UX Engineer**.

Your task is to design and develop a production-quality application called **ResearchMind AI**.

# 1. Project Overview

Build an intelligent **Personal Autonomous Research & R&D AI Agent** that can research almost any topic on behalf of the user using the internet.

The user should be able to enter a simple request such as:

> Research the best approaches for AI-powered desktop application testing. Focus on offline deployment, Java compatibility, Windows support, local LLM integration, computer vision, GitHub projects, research papers, and existing solutions. Compare the available approaches and recommend what I should build.

The system must autonomously perform the complete research process instead of simply returning a normal chatbot answer.

The application should:

1. Understand the user's research objective.
2. Identify the topic and scope.
3. Extract constraints and preferences.
4. Break the research into multiple questions.
5. Generate a research plan.
6. Create research tasks.
7. Search multiple sources on the internet.
8. Research official documentation.
9. Research GitHub repositories.
10. Research research papers and academic sources.
11. Research recent news and trends when required.
12. Extract relevant information from sources.
13. Remove duplicate information.
14. Verify important claims.
15. Detect conflicting information.
16. Identify knowledge gaps.
17. Automatically perform follow-up research when gaps exist.
18. Analyze all collected information.
19. Compare possible solutions.
20. Generate practical recommendations.
21. Generate a detailed R&D report with sources and evidence.

The goal is to create an AI system that behaves like a **personal research team and R&D analyst**, not merely a search engine or chatbot.

---

# 2. Core Product Concept

The overall workflow should be:

```text
USER RESEARCH REQUEST
        │
        ▼
UNDERSTAND USER INTENT
        │
        ▼
RESEARCH PLANNER AGENT
        │
        ▼
GENERATE RESEARCH QUESTIONS
        │
        ▼
CREATE RESEARCH PLAN
        │
        ▼
CREATE RESEARCH TASKS
        │
        ▼
PARALLEL RESEARCH AGENTS
        │
        ├── Web Research Agent
        ├── Official Documentation Agent
        ├── GitHub Research Agent
        ├── Academic Paper Agent
        ├── News & Trends Agent
        └── Community Research Agent
        │
        ▼
SOURCE COLLECTION
        │
        ▼
CONTENT EXTRACTION
        │
        ▼
DUPLICATE DETECTION
        │
        ▼
SOURCE QUALITY SCORING
        │
        ▼
CLAIM VERIFICATION
        │
        ▼
CONFLICT DETECTION
        │
        ▼
KNOWLEDGE GAP ANALYSIS
        │
        ├── GAP FOUND?
        │        │
        │       YES
        │        ▼
        │   FOLLOW-UP RESEARCH
        │        │
        └────────┘
        │
        ▼
R&D ANALYSIS
        │
        ▼
SOLUTION COMPARISON
        │
        ▼
RECOMMENDATION ENGINE
        │
        ▼
FINAL RESEARCH REPORT
```

---

# 3. Technology Stack

Use the following architecture unless there is a strong technical reason to improve it.

## Frontend

- React
- TypeScript
- Vite or Next.js
- Tailwind CSS
- shadcn/ui
- Responsive design
- Modern dashboard UI

## Backend

- Python
- FastAPI
- Pydantic
- SQLAlchemy

## AI and Agent System

- LangGraph or an equivalent stateful agent orchestration architecture
- Support for multiple AI providers
- Local LLM support
- Cloud LLM support

## Local AI

Primary local AI integration:

- Ollama

The architecture must allow support for models such as:

- Llama
- Qwen
- Mistral
- Gemma
- Other future Ollama models

The system must not be tightly coupled to one specific model.

## Database

- PostgreSQL

Use SQLite for simple local development if required.

## Vector Database

- Qdrant

Use it for:

- Research memory
- Semantic search
- Previous research retrieval
- Knowledge reuse
- Finding similar research projects

## Cache and Queue

- Redis

Use background workers for long-running research.

## Reports

Support generation of:

- Web report
- Markdown
- HTML
- PDF
- DOCX

---

# 4. Multi-Agent Architecture

Create the following agents.

## Agent 1: Research Manager Agent

This is the main orchestrator.

Responsibilities:

- Understand the original request.
- Coordinate all agents.
- Monitor research progress.
- Decide whether more research is required.
- Combine findings.

The Research Manager must maintain a complete research state.

Example state:

```text
Research ID
Research Goal
User Query
Research Mode
Scope
Constraints
Research Questions
Research Tasks
Sources
Findings
Claims
Conflicts
Knowledge Gaps
Recommendations
Research Status
Progress Percentage
```

---

## Agent 2: Research Planner Agent

Convert the user's natural language request into a structured research plan.

Example input:

```text
Research AI-powered desktop automation.
Focus on Windows, Java, offline AI and computer vision.
```

Example output:

```text
Research Objective:
Identify the best architecture for AI-powered desktop automation.

Research Questions:

1. What existing AI desktop automation solutions exist?
2. Which open-source solutions are available?
3. Which solutions support Windows?
4. Which solutions can operate offline?
5. Which technologies support Java integration?
6. Can computer vision improve desktop automation?
7. Can local LLMs improve automation intelligence?
8. What are the limitations of current solutions?
9. What architecture is recommended?
10. What proof of concept should be developed first?
```

The plan must be editable by the user before research starts if the user chooses manual approval mode.

---

## Agent 3: Web Research Agent

Search the web for:

- Technical articles
- Industry websites
- Expert analysis
- Tutorials
- Product information
- Technology documentation

The agent must collect:

```text
Title
URL
Publisher
Author
Publication Date
Source Type
Extracted Content
Summary
Relevant Claims
Authority Score
Relevance Score
```

---

## Agent 4: Official Documentation Agent

Prioritize authoritative information.

Research:

- Official product documentation
- Official APIs
- Official company documentation
- Standards documentation
- Government sources when relevant

Official sources should receive higher reliability scores.

---

## Agent 5: GitHub Research Agent

Research relevant open-source projects.

For each repository, analyze:

```text
Repository Name
Repository URL
Owner
Description
Programming Language
License
Stars
Forks
Last Commit
Latest Release
Open Issues
Documentation Quality
Project Activity
Community Activity
Main Features
Advantages
Limitations
Relevance Score
```

The agent should distinguish between:

- Active projects
- Inactive projects
- Experimental projects
- Production-ready projects

---

## Agent 6: Academic Research Agent

Research:

- Academic papers
- arXiv papers
- IEEE publications
- ACM publications
- University research

For each paper, extract:

```text
Paper Title
Authors
Publication Date
Research Problem
Methodology
Technology Used
Results
Limitations
Key Findings
Relevance
```

Do not merely collect paper titles. Analyze the practical relevance of each paper.

---

## Agent 7: News and Trends Agent

Use this agent only when freshness matters.

Examples:

- Latest technology releases
- Recent AI developments
- Product announcements
- Industry changes
- Recent security issues
- Market developments

The agent must clearly show the date of each finding.

---

## Agent 8: Community Research Agent

Research community experiences from appropriate sources.

Possible areas:

- Developer communities
- Forums
- Reddit discussions
- Stack Overflow
- GitHub issues

Community information must not be treated as equally authoritative as official documentation.

Clearly label:

```text
Community Opinion
Verified Fact
Unverified Claim
Personal Experience
```

---

# 5. Source Reliability System

Implement a source scoring system.

Example:

```text
Official Documentation        100
Government / Standards         95
Peer Reviewed Research         95
University Research            90
Official GitHub Repository     90
Established Technical Source   80
Major News Organization        80
Community Discussion           60
Personal Blog                  40
Unknown Source                 20
```

The final score should also consider:

- Source authority
- Publication date
- Relevance
- Citations
- Cross-source agreement
- Author credibility

Do not blindly trust a source simply because it appears first in search results.

---

# 6. Claim Verification System

Implement structured claims.

Example:

```json
{
  "claim": "Technology X supports offline deployment",
  "sources": [
    "Official Documentation",
    "GitHub Documentation",
    "Technical Article"
  ],
  "status": "VERIFIED",
  "confidence": 92
}
```

Claim statuses:

```text
VERIFIED
PARTIALLY_VERIFIED
CONFLICTED
UNVERIFIED
INSUFFICIENT_EVIDENCE
```

Important recommendations should be based primarily on verified or highly supported evidence.

---

# 7. Conflict Detection

The system must identify contradictions.

Example:

```text
CLAIM A:
Tool supports Windows.

SOURCE:
Official documentation.

CLAIM B:
Tool only supports Linux.

SOURCE:
Community forum.

CONFLICT STATUS:
Needs verification.

ACTION:
Search official compatibility documentation and recent releases.
```

The agent must not hide conflicts.

The final report should include unresolved conflicts when they materially affect the recommendation.

---

# 8. Knowledge Gap Analysis

After initial research, analyze every important research question.

Example:

```text
Question:
Does the solution support Java integration?

Available Information:
Python integration: Strong evidence
Java integration: Insufficient evidence

STATUS:
KNOWLEDGE GAP DETECTED

FOLLOW-UP TASK:
Research official Java SDKs, APIs and integration examples.
```

The system must automatically create follow-up tasks when necessary.

This is a core feature.

The research loop should continue until:

```text
All critical questions answered
OR
Maximum research depth reached
OR
Maximum source/task budget reached
OR
No new meaningful information is being discovered
```

---

# 9. Research Modes

Implement the following modes.

## Quick Research

- Small number of sources
- Fast execution
- Short report

## Standard Research

- Multiple source types
- Moderate verification
- Detailed report

## Deep Research

- Multi-agent workflow
- Follow-up research
- Claim verification
- Conflict detection
- Gap analysis
- Comprehensive report

## Technical R&D

Optimized for:

- Software
- AI
- Architecture
- APIs
- Libraries
- Frameworks
- Proof of concept
- Implementation decisions

The report should include:

```text
Available Technologies
Architecture Options
Comparison
Advantages
Disadvantages
Technical Risks
Implementation Complexity
Recommended Architecture
Proof of Concept Plan
```

## Comparison Mode

Compare multiple products, technologies, or approaches.

## Decision Mode

Research available options and recommend the best option according to user-defined criteria.

---

# 10. Research Dashboard

Create a professional dashboard.

Main navigation:

```text
Dashboard
New Research
Research History
Knowledge Base
Saved Findings
Reports
Monitoring
Settings
```

Dashboard should show:

```text
Total Research Projects
Research Completed
Research In Progress
Verified Findings
Saved Sources
Knowledge Base Size
```

Recent research projects should be displayed.

---

# 11. New Research Screen

The main research input screen should contain:

```text
What do you want me to research?

[ Large Research Input Area ]

Research Mode:
○ Quick
○ Standard
○ Deep Research
○ Technical R&D
○ Comparison
○ Decision

Research Sources:
☑ Web
☑ Official Documentation
☑ GitHub
☑ Research Papers
☑ News
☑ Community

Additional Constraints:
[____________________________]

Time Range:
○ Any Time
○ Last 30 Days
○ Last Year
○ Custom

[ Start Research ]
```

The interface should also allow the user to specify:

- Budget
- Location
- Technology preferences
- Programming language
- Online/offline requirement
- Open-source requirement
- Commercial requirement

---

# 12. Live Research Activity Screen

Show real-time research progress.

Example:

```text
Research:
AI-Powered Desktop Automation

Overall Progress:
████████████████░░░░ 80%

✓ Understanding objective
✓ Creating research plan
✓ Generating research questions
✓ Searching official documentation
✓ Searching GitHub repositories
✓ Searching research papers
✓ Collecting web sources
✓ Extracting findings
✓ Verifying claims

⏳ Detecting conflicts
○ Knowledge gap analysis
○ R&D analysis
○ Final report generation
```

Show live agent activities:

```text
Research Planner:
Created 12 research questions.

Web Agent:
Analyzing 24 relevant sources.

GitHub Agent:
Evaluating 16 repositories.

Academic Agent:
Reading 8 relevant papers.

Verification Agent:
Checking 42 important claims.
```

Allow the user to:

- Pause research
- Resume research
- Stop research
- Add a new question
- Exclude a source
- Prioritize a research question

---

# 13. Research Report

Generate a high-quality report containing:

# Executive Summary

A concise overview.

# Research Objective

What was researched and why.

# Research Scope

Boundaries of the research.

# Research Questions

List all questions investigated.

# Key Findings

Most important discoveries.

# Detailed Analysis

Detailed explanation of findings.

# Technology or Solution Comparison

Use tables where appropriate.

# Verified Claims

Show high-confidence evidence.

# Conflicting Information

Show unresolved contradictions.

# Knowledge Gaps

Clearly identify unanswered questions.

# Advantages

# Limitations

# Risks

# Recommended Solution

Give a clear recommendation.

# Why This Recommendation

Explain the reasoning.

# Alternative Solutions

Include alternatives.

# Implementation Roadmap

Provide practical next steps.

# Proof of Concept

When relevant, recommend a small experiment to validate the solution.

# Sources

List sources with:

```text
Title
Publisher
Date
Source Type
Reliability Score
URL
```

# Research Confidence

Example:

```text
Overall Research Confidence: 91%

Sources Analyzed: 48
Official Sources: 15
GitHub Sources: 10
Research Papers: 7
Community Sources: 8
Other Sources: 8

Verified Claims: 36
Conflicted Claims: 3
Unverified Claims: 4
```

---

# 14. Personal Knowledge Base

Implement a long-term research knowledge system.

The system should store:

- Previous research projects
- Verified claims
- Important findings
- Recommendations
- Technical decisions
- Architecture decisions
- Saved sources

When new research starts, search the existing knowledge base.

Example:

```text
NEW RESEARCH:
AI Agent for Desktop Testing

RELATED PREVIOUS RESEARCH FOUND:
Local LLM Integration
Computer Vision for Automation
OCR-Based Testing

RELEVANT KNOWLEDGE CAN BE REUSED.
```

Do not blindly reuse old information.

Old knowledge must be revalidated if freshness is important.

---

# 15. Research Memory and Knowledge Graph

Create relationships between:

```text
Research Project
     │
     ├── Topic
     ├── Technology
     ├── Source
     ├── Finding
     ├── Claim
     ├── Recommendation
     └── Decision
```

Example:

```text
Local LLM
    │
    ├── Ollama
    │
    ├── Automation
    │       │
    │       ├── Selenium
    │       ├── Winium
    │       └── Playwright
    │
    └── AI Agent
            │
            ├── Computer Vision
            ├── OCR
            └── Object Detection
```

---

# 16. Backend API Design

Create REST APIs for:

```text
POST   /research
GET    /research
GET    /research/{id}
POST   /research/{id}/start
POST   /research/{id}/pause
POST   /research/{id}/resume
POST   /research/{id}/stop

GET    /research/{id}/plan
PUT    /research/{id}/plan

GET    /research/{id}/questions
POST   /research/{id}/questions

GET    /research/{id}/tasks

GET    /research/{id}/sources
GET    /research/{id}/findings
GET    /research/{id}/claims
GET    /research/{id}/conflicts
GET    /research/{id}/recommendations

GET    /research/{id}/report
POST   /research/{id}/export

GET    /knowledge/search
GET    /knowledge/related
POST   /knowledge/save
```

Also implement WebSocket or Server-Sent Events for real-time agent activity.

---

# 17. Database Schema

Create tables for:

```text
users
research_projects
research_plans
research_questions
research_tasks
agents
agent_executions
sources
source_contents
findings
claims
claim_sources
conflicts
knowledge_gaps
recommendations
reports
saved_findings
knowledge_items
knowledge_relationships
```

All major tables should include:

```text
id
created_at
updated_at
```

Use proper foreign keys and indexes.

---

# 18. Suggested Project Structure

Use a clean architecture.

```text
researchmind-ai/

├── frontend/
│   ├── src/
│   │   ├── components/
│   │   ├── pages/
│   │   ├── features/
│   │   ├── hooks/
│   │   ├── services/
│   │   ├── store/
│   │   └── types/
│   └── package.json
│
├── backend/
│   ├── app/
│   │   ├── api/
│   │   ├── core/
│   │   ├── database/
│   │   ├── models/
│   │   ├── schemas/
│   │   ├── services/
│   │   ├── agents/
│   │   │   ├── research_manager/
│   │   │   ├── research_planner/
│   │   │   ├── web_research/
│   │   │   ├── documentation/
│   │   │   ├── github_research/
│   │   │   ├── academic_research/
│   │   │   ├── news_research/
│   │   │   ├── community_research/
│   │   │   ├── verification/
│   │   │   ├── conflict_detection/
│   │   │   ├── gap_analysis/
│   │   │   └── rd_analysis/
│   │   │
│   │   ├── workflows/
│   │   ├── tasks/
│   │   ├── repositories/
│   │   └── utils/
│   │
│   ├── tests/
│   └── requirements.txt
│
├── infrastructure/
│   ├── docker/
│   └── deployment/
│
├── docs/
│   ├── architecture/
│   ├── api/
│   └── development/
│
└── README.md
```

---

# 19. Agent Workflow Requirements

The agent system must be stateful.

A research project should maintain its state even if:

- The server restarts.
- Research is paused.
- A task fails.
- The user returns later.

Each task should have a status:

```text
PENDING
QUEUED
RUNNING
COMPLETED
FAILED
RETRYING
PAUSED
CANCELLED
```

Implement retry logic.

Failed tasks should not destroy the entire research project.

---

# 20. Error Handling

Handle:

- Search API failures
- Invalid URLs
- Website timeouts
- Rate limits
- Blocked websites
- Duplicate sources
- LLM failures
- Ollama connection failures
- Invalid model responses
- Database failures
- Queue failures

Display meaningful error messages to the user.

Example:

```text
GitHub Research Agent temporarily failed.

Reason:
API rate limit reached.

Action:
Task will automatically retry in 5 minutes.
```

---

# 21. Security Requirements

Implement:

- Authentication
- JWT or secure session handling
- Password hashing
- API key encryption
- Environment variables
- Rate limiting
- Input validation
- URL validation
- SSRF protection
- Access control
- Audit logging

Never expose API keys to the frontend.

---

# 22. Local LLM Support

Create an AI provider abstraction.

Example:

```text
AIProvider
├── OllamaProvider
├── OpenAIProvider
├── AnthropicProvider
└── FutureProvider
```

Each provider should support:

```text
generate()
stream()
structured_output()
health_check()
list_models()
```

The application should work with a local Ollama server.

Include a settings screen where the user can configure:

```text
Ollama Base URL
Selected Model
Temperature
Maximum Tokens
Cloud Provider
API Key
Fallback Provider
```

---

# 23. Important Development Rules

Follow these rules strictly.

1. Do not create a fake multi-agent system where every agent is only a prompt.
2. Use structured task objects and persistent research state.
3. Separate research collection from AI reasoning.
4. Do not trust a single source for important claims.
5. Prefer primary and authoritative sources.
6. Clearly show uncertainty.
7. Do not invent facts or sources.
8. Preserve source URLs and metadata.
9. Make every major recommendation traceable to evidence.
10. Do not hide conflicting information.
11. Automatically perform follow-up research for critical knowledge gaps.
12. Support cancellation and resumption.
13. Design the system to be extensible.
14. Avoid tightly coupling the application to one LLM provider.
15. Build the MVP first before implementing every advanced feature.

---

# 24. Development Phases

## Phase 1: Foundation

Develop:

- Project setup
- Database
- Authentication
- Frontend dashboard
- New research page
- Research project management

## Phase 2: Basic Research

Develop:

- Research Planner
- Web Research Agent
- Source collection
- Source storage
- Finding extraction
- Basic AI analysis

## Phase 3: Deep Research

Develop:

- GitHub Research Agent
- Documentation Agent
- Academic Research Agent
- News Agent
- Parallel task execution

## Phase 4: Research Intelligence

Develop:

- Claim verification
- Conflict detection
- Duplicate detection
- Knowledge gap analysis
- Automatic follow-up research

## Phase 5: R&D Intelligence

Develop:

- Solution comparison
- Recommendation engine
- Architecture analysis
- Proof-of-concept recommendations
- Implementation roadmap generation

## Phase 6: Knowledge System

Develop:

- Research memory
- Semantic search
- Knowledge reuse
- Knowledge graph

## Phase 7: Production Features

Develop:

- Report export
- Monitoring
- Scheduled research
- Notifications
- Performance optimization
- Security hardening

---

# 25. Acceptance Criteria

The first working version must allow a user to:

1. Create a research project.
2. Enter a research request.
3. Select Deep Research mode.
4. Generate a research plan.
5. Generate multiple research questions.
6. Execute multiple research tasks.
7. Collect multiple web sources.
8. Display live research progress.
9. Store sources and findings.
10. Generate a structured final report.
11. Show sources used in the report.
12. Save the project.
13. Resume the project later.
14. Search previous research.

The Deep Research version must additionally:

1. Use multiple specialized agents.
2. Perform parallel research.
3. Research multiple source types.
4. Verify important claims.
5. Detect conflicts.
6. Identify knowledge gaps.
7. Automatically create follow-up research tasks.
8. Generate evidence-based recommendations.

---

# 26. Development Instructions

Start by analyzing this complete requirement.

Then:

1. Propose the final architecture.
2. Identify missing technical decisions.
3. Create the project structure.
4. Implement the database schema.
5. Implement the FastAPI backend foundation.
6. Implement the React frontend foundation.
7. Implement the Research Project workflow.
8. Implement the Research Planner.
9. Implement the Web Research Agent.
10. Implement persistent task execution.
11. Implement real-time progress updates.
12. Implement source storage.
13. Implement the first working research report.
14. Test the complete end-to-end workflow.
15. Only then proceed to advanced agents.

Do not attempt to implement everything in one unstructured step.

Build incrementally.

After each major phase:

- Verify functionality.
- Fix errors.
- Avoid breaking existing features.
- Keep the application runnable.

Use clean, production-quality code with proper separation of concerns.

The final application should feel like having a team of autonomous researchers, technical analysts, and R&D engineers working on behalf of the user.

**Begin by creating the complete project architecture and implementing Phase 1.**