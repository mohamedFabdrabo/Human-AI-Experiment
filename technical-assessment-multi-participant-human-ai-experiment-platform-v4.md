# Technical Assessment: Multi-Participant Human-AI Experiment Platform

**Position:** Student Research Assistant – Full-Stack Developer (Center for Humans and Machines, MPIB)

**Timeline:** 7 days from receipt (Expected effort: **no more than 4 hours**)

**Submission:** Link to a public GitHub repository sent prior to your interview

## 1. Overview & Goal

At the Center for Humans and Machines, we build real-time experimental platforms to study human-AI interaction. For this assessment, your goal is to build a lightweight web application simulating a **3-participant group decision-making experiment**.

**Time Expectation & Scope:** This task is strictly scoped to take **no more than 4 hours**. Some edge cases and implementation details are intentionally left open-ended—we want to see how you use your own common sense, architectural judgment, and AI tooling to make pragmatic decisions under time constraints.

**AI-Assisted Development:** You are encouraged to use AI coding agents/assistants (e.g., Cursor, Claude Code, Copilot, ChatGPT) to build this project. How you steer and collaborate with your AI tools is a core part of what we are evaluating.

## 2. Experiment Flow & Rules

* **Participants & Anonymity:**
  * Each session involves **3 participants** with neutral identifiers (e.g., *Player A*, *Player B*, *Player C*).
  * **Blind Condition:** Participants must **not** know whether the other participants are humans or AI agents.
* **Waiting Room:** Human participants should land in a waiting room until all required human slots for the session are filled, after which the experiment begins.
* **Rounds & Voting:**
  * Participants go through **2 rounds** of real-time text discussion (around **1 minute per round**). Their goal is to discuss and decide who among the 3 of them should be elected as the **Decision Maker** for a subsequent (imaginary) experiment.
  * At the end of each round, participants vote for one of the 3 participants.
  * Once voting concludes, the **final results** and selected Decision Maker are displayed to all participants. *(How you handle intermediate round feedback, tie-breaking, and AI agent behavior/responses is up to your discretion—document your choices briefly).*

## 3. Configuration & Technical Stack

* **YAML Configuration (`config.yml`):** Experiment parameters and participant types (`human` vs. `ai`) should be configured via a `.yml` file so we can easily test all 3 conditions without changing code:
  1. **3 Humans**
  2. **2 Humans + 1 AI Agent**
  3. **1 Human + 2 AI Agents**
* **Stack:**
  * **Frontend:** React
  * **Backend:** Python - Fast API
  * **Database:** MongoDB or Postgresql
  * **Containerization:** Dockerized so the entire application can be started locally with a single command.

## 4. Submission & Interview Format

1. **GitHub Repository (Due within 7 days):** Share a link to a **public GitHub repository** containing:
   * Your source code, `config.yml`, and Docker setup.
   * A concise `README.md` explaining how to run the project, switch configurations, and any key design decisions or trade-offs made within the **4-hour** limit.
   * **AI Usage Log:** A file or folder in the repository (e.g., `ai_prompts.md` or `ai_logs/`) containing **all prompts** from your conversations with your AI assistant(s), along with the **exact model(s) and agent/tool(s)** you used.
   * Send the link to the Git Repository in response to this email.
2. **Online Interview (5-Minute Presentation + Demo):**
   * Prepare a short **slide deck** to present your **development process in 5 minutes** (how you broke down the problem, prompted/guided your AI agent, resolved issues, and made trade-offs).
   * Be ready to run the app locally via Docker, demonstrate the flow, and discuss your codebase.