# Demo script (about 6 minutes)

Start the backend and frontend (see README), open http://localhost:3000. Numbers below come from the demo data with the built-in solver; re-run before presenting if you change data.

**Login → existing schedule → disruption → Repair Centre → constraint analysis → recommended repair → reasoning → approval → updated schedule → employee dashboard → recognition**

## 1. The pitch (15 s)
> "When someone can't make their shift, most tools either do nothing or rebuild the whole roster. ResQWork repairs the schedule you already have with the smallest valid change, and when no valid change exists, it says so."

Point at the hero grid: one cell breaks and exactly one cell changes.

## 2. The employee asks (45 s)
1. Under **Try it with realistic data → Healthcare**, sign in as **Rahul Sharma** (employee).
2. His dashboard answers "what am I working on / what changed / do I need to act / what's pending" at a glance.
3. **New request** → *Can't work*, Fri 9 Oct, whole day, note "Fever since last night" → **Send request**. Status: **Pending**.

## 3. The manager decides (60 s)
1. Header switcher → **Manager: Nurse manager**. The Hospital Command Center shows the request and the *Employee requests* badge.
2. **Employee requests → Approve** (note "Get well soon"). Switch back to Rahul to show **Approved** with the note, then return to the manager. This is one shared request record, not two copies.

## 4. Repair Centre (90 s)
1. On the command center, the absence is now an open disruption → **Generate repair**.
2. Walk down the page:
   - **Progress strip:** disruption → impact → constraints validated → candidates → best repair → approval.
   - **Problem / Impact:** Rahul unavailable (availability rule); ICU Day Fri 07:00–19:00 (critical) needs cover.
   - **Constraint analysis:** hard rules (all ✓) vs soft goals with their weights.
   - **Options:** A *Recommended* (Neha Joshi, 1 change, 0h overtime, impact 5.6%) and B *Highest fairness* (2-step chain). Rebuilding from scratch would change 13–15.
3. Hover **Neha Joshi**: *"selected because they have RN, ICU Care, ACLS, are available Fri 07:00–19:00… 12h → 24h (limit 48h), no overtime."* Hover the fairness score and the impact %.
4. **View details:** Elena ruled out by the rest rule (0h after her night shift), Hannah by 12h overtime, Aisha for no ICU Care.
5. **Compare** to show A vs B side by side, then **Approve repair** → schedule v1.1 is published and 1 staff member notified.

## 5. Employees see it (45 s)
1. Switch to **Employee: Neha Joshi**: *What changed for you* shows ICU Day added, marked **New** in her week → **Acknowledge**.
2. Her **Recognition** card: *Shift Rescue* and *Critical Care Support* for covering, *Reliability* for acknowledging quickly. Overtime would have earned nothing extra.
3. Switch to Rahul: his request now shows **Completed**.

## 6. Recognition and voice (40 s)
1. Manager → **Recognition**: the domain-specific categories and tiers. **Recognize** someone for *Patient Safety Champion* with a note.
2. **Voice agent:** say or type *"Why was Neha Joshi reassigned?"* The answer comes from the solver's evidence and opens the Repair Centre. Try *"What changed in the latest repair?"* and *"Show today's schedule"*. With `GEMINI_API_KEY` set, the mic records and Gemini transcribes; without it, Chrome's speech recognition or typing works.

## 7. When it can't be done (60 s), the differentiator
1. **Switch industry / dataset → Continue → Scenario Plant: infeasible**, then **Simulate**: the only free CNC-certified operator is unavailable.
2. The Repair Centre shows **No feasible repair exists under the current constraints**:
   - Funnel: 5 checked → 3 have CNC Operation → 2 hold Safety Level 2 → 1 available → **0** not already on an overlapping mandatory line.
   - Bottleneck: Bala Krishnan is running Line 2. Near misses: Asha (availability only), Chitra (certification only).
   - Resolutions: ask Asha, free up Bala, or *relax the certification (manual override, not applied automatically)*.
3. Nothing illegal is assigned, and voice approval refuses. Publishing the partial repair needs an explicit override with a reason.

## 8. Conflicts in uploaded data (30 s)
**Scenario Plant: repair cases**: the command center flags *Double-booked: Bala Krishnan* (Task C and Task B at the same time) → **Repair conflicts** → Esha Menon takes Task B (1 change). Approve, and both Bala and Esha are notified.

## Close (15 s)
> "AI understands and explains, the optimizer decides, the manager approves, and when the rules make it impossible, ResQWork says so instead of faking it."

## Demo accounts

| Industry | Manager | Employee who covers | Employee who is out |
|---|---|---|---|
| Healthcare | manager@healthcare.demo | neha@healthcare.demo | rahul@healthcare.demo |
| Manufacturing | manager@manufacturing.demo | kiran@manufacturing.demo | ravi@manufacturing.demo |
| Education | manager@education.demo | kavitha@education.demo | anjali@education.demo |
| Technology | manager@technology.demo | kunal@technology.demo | rohit@technology.demo |
| Logistics | manager@logistics.demo | ganesh@logistics.demo | ramesh@logistics.demo |

Password for all: `demo1234`. `admin@<industry>.demo` also exists. **Reset this demo** on the landing page restores the starting data.
