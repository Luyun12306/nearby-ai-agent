# Nearby AI — Home Service Provider Agent

## Overview

Build an AI-powered agent that helps homeowners identify their home service needs and connect with suitable local service providers.

The agent should engage users in natural conversations, understand their problems, recommend appropriate service providers, and ultimately generate actionable leads that can be dispatched to real businesses.

## 1. Project Objective

Develop a conversational AI agent that can:

1. Understand a homeowner's problem through natural language.
2. Ask relevant follow-up questions to clarify the issue.
3. Identify the appropriate home service category.
4. Find suitable service providers in the user's local area.
5. Recommend providers based on the user's needs.
6. Collect necessary information to generate a dispatchable lead.

### Example User Scenario

**User:**
> Water started coming into my basement last night after the storm. I don't know who to call.

**Expected Agent Behavior:**

1. Understand the reported water intrusion problem.
2. Ask clarifying questions about severity, location, and urgency.
3. Determine the appropriate service category.
4. Retrieve relevant local service providers.
5. Recommend suitable providers.
6. Collect the information needed to create a lead.
7. Generate a structured lead that could be dispatched to a real provider.

## 2. Core Requirements

### 2.1 Conversational AI Agent

The agent must support natural, multi-turn conversations.

It should be able to:

- Understand user intent.
- Identify the underlying home service problem.
- Ask relevant follow-up questions.
- Maintain conversation context.
- Guide users toward an appropriate service provider.

### 2.2 Local Service Provider Discovery

The system must use real service provider data from the local area.

**Important:**

- Providers must be real businesses.
- Provider information should be accurate.
- Returned providers may be independently verified.
- Fake or fabricated provider information is not acceptable.

### 2.3 Provider Matching

The agent should identify providers suitable for the user's specific problem.

Potential matching factors include:

- Service category
- Geographic location
- Problem severity
- Urgency
- Provider specialization

### 2.4 Lead Generation

The conversation should ultimately produce a lead that could be dispatched to a real service provider.

A useful lead may include:

- Customer contact information
- Service location
- Problem description
- Service category
- Urgency
- Relevant conversation details
- Recommended provider

The goal is to produce actionable leads rather than simply provide general recommendations.

## 3. Primary Evaluation Metrics

The two most important business outcomes are:

### 3.1 Conversion Rate

**Definition:**

The percentage of conversations that successfully result in dispatchable leads.

```text
Conversion Rate =
    Number of Conversations Producing Dispatchable Leads
    ----------------------------------------------------
                Total Number of Conversations
```

The agent should guide users efficiently from problem identification to lead creation.

### 3.2 Lead Quality

**Definition:**

Whether a real service provider would accept and act on the generated lead.

A high-quality lead should contain sufficient information for the provider to understand the job and determine whether to accept it.

The system should prioritize actionable, relevant, and complete leads.

## 4. Technical Guidelines

### AI Development Tools

Any AI-assisted development tools may be used, including:

- Claude Code
- OpenAI Codex
- Cursor
- Other preferred development tools

The evaluation focuses on whether the solution works, not on who or what wrote the code.

### Time Constraints

**Expected development time: approximately 10 hours.**

The assignment is intentionally time-boxed.

Candidates are not expected to spend significantly more than 10 hours.

Prioritize working functionality over unnecessary complexity.

### UI Requirements

Visual polish is not a priority.

Focus on:

- Functional correctness
- Reliable agent behavior
- Provider matching
- Lead generation
- Demonstrable end-to-end functionality

## 5. Suggested End-to-End Workflow

```text
User Describes Home Problem
            |
            v
    Conversational Agent
            |
            v
    Problem Understanding
            |
            v
    Clarifying Questions
            |
            v
    Service Classification
            |
            v
    Local Provider Retrieval
            |
            v
    Provider Matching
            |
            v
    Provider Recommendation
            |
            v
    Customer Information Collection
            |
            v
    Structured Lead Generation
            |
            v
       Dispatchable Lead
```

This workflow is a suggested implementation approach, not a mandated architecture.

## 6. Deliverables

Submit whatever best demonstrates that the solution works.

Possible deliverables include:

- Source code
- README documentation
- Setup and execution instructions
- Working application or CLI demo
- Example conversations
- Generated lead examples
- Test cases or evaluation results

No specific submission format is required.

## 7. Time Management and Future Improvements

If the implementation cannot be completed within the recommended time, document:

1. What has been implemented.
2. What remains incomplete.
3. Which features would be prioritized next.
4. How the solution could be improved.

Clearly distinguish implemented functionality from planned improvements.

## 8. Success Criteria

A successful solution should demonstrate that:

- Users can describe home service problems naturally.
- The agent can conduct useful follow-up conversations.
- The agent identifies appropriate service categories.
- Recommendations use real local service providers.
- Provider recommendations are relevant to user needs.
- Conversations can produce actionable, dispatchable leads.
- The solution can be demonstrated and evaluated.

## 9. Key Priorities

The assignment emphasizes:

**1. Working End-to-End Experience**

The agent should successfully guide users from describing a problem to generating a lead.

**2. Real Provider Data**

Provider recommendations must correspond to actual local businesses.

**3. Conversion Rate**

The system should effectively convert conversations into dispatchable leads.

**4. Lead Quality**

Generated leads should contain information that makes them useful to real service providers.

**5. Practical Engineering**

Build a functional, demonstrable solution within approximately 10 hours.

---

## Assignment Context

**Company:** Nearby AI (NewsBreak)

**Track:** Engineering Internship

**Assignment:** AI Agent for Home Service Provider Discovery

**Estimated Time:** 10 hours

**AI Tools:** Allowed

**Visual Polish:** Not evaluated as a priority

**Primary Metrics:** Conversion Rate & Lead Quality