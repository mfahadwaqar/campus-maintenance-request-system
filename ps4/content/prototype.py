PROTOTYPE = {
    "intro": (
        "The screens below are the current Campus Maintenance interface, shown with synthetic sample data. "
        "They cover one task end to end: a resident reports a fault, Call Center Staff review and assign it, "
        "the Technician/Contractor completes it, and the resident verifies or reopens it."
    ),
    "screens": [
        {"figure": "Figure 4", "label": "Resident request submission", "image": "ps4/prototype/fig4.png",
         "note": "Resident fills in category, building, room and a description. Sample data."},
        {"figure": "Figure 5", "label": "Resident verification", "image": "ps4/prototype/fig5.png",
         "note": "A completed request shows the progress line, a verify form and a reopen form."},
        {"figure": "Figure 6", "label": "Call Center Staff queue", "image": "ps4/prototype/fig6.png",
         "note": "Queue with status, priority, category, building and follow-up filters. There is no search by room or student ID."},
        {"figure": "Figure 7", "label": "Technician/Contractor work order", "image": "ps4/prototype/fig7.png",
         "note": "Work order offers only 'Mark complete'. There is no way to put work on hold."},
        {"figure": "Figure 8", "label": "Status history", "image": "ps4/prototype/fig8.png",
         "note": "Every status change with time and actor."},
        {"figure": "Figure 9", "label": "Reopened ticket in officer queue", "image": "ps4/prototype/fig9.png",
         "note": "The reopened request is highlighted and offers 'Reassign technician'."},
    ],
    "session": {
        "date": "11 November 2026",
        "mode": "in person, joint session with OFAM staff and the technical side",
        "duration": "about 22 minutes (audio recorded with permission; not published)",
        "concept_shown": (
            "Two printed workflow diagrams of the proposed process (one for Call Center Staff, one for the "
            "Technician/Contractor), in English with a Thai translation. They are the storyboard behind "
            "Figures 4 to 9."
        ),
        "task_prompt": (
            "Please walk us through what happens to a request from submission to closure. Tell us which "
            "steps are right, which are wrong or missing, and what you would change."
        ),
    },
    "participants": [
        {"code": "S1", "user_class": "OFAM Call Center Staff"},
        {"code": "C1", "user_class": "Contractor side (unit supervisor)"},
        {"code": "T1", "user_class": "Technician"},
    ],
    "steps": [
        {"step": "Request arrives (website, email, phone, walk-in)", "rating": "Understandable", "who": "S1",
         "observation": "S1 confirmed the four channels and treated the first steps as correct.",
         "implication": "Keep the resident form (Figure 4). Staff entry on behalf of a caller is still needed."},
        {"step": "Find an earlier ticket when the caller has no ticket number", "rating": "Missing", "who": "S1",
         "observation": "Callers rarely know the ticket number. Staff look it up by room number, student ID or mobile number.",
         "implication": "Add search by room, student ID and ticket number to the queue (Figure 6). It has only filters today."},
        {"step": "Put work on hold while waiting for spare parts", "rating": "Missing", "who": "S1, T1",
         "observation": "When a part is out of stock, the resident is told the work is waiting and for roughly how long. T1 described waiting for parts from the store.",
         "implication": "Add a hold action with reason and expected date to the work order (Figure 7). The back end supports it; the screen does not."},
        {"step": "Mark work complete", "rating": "Confusing", "who": "S1, T1",
         "observation": "Technicians hand the receipt to the contractor, who finishes jobs in one batch after a few days with no repeat complaint. The app completes one ticket at a time.",
         "implication": "Keep per-ticket completion for now. Note batch completion as a later option after confirming the practice."},
        {"step": "Resident survey and closure", "rating": "Confusing", "who": "S1",
         "observation": "S1 gave different answers on closing when the resident does not reply: three days, then immediately. The earlier OFAM interview said 15 days.",
         "implication": "Make the closure period a setting, keep 15 days by default and ask OFAM to confirm (Figure 5)."},
        {"step": "Reopen an unsatisfactory job", "rating": "Understandable", "who": "S1",
         "observation": "S1 said an unhappy resident reopens the ticket and it goes back to in progress.",
         "implication": "Keep reopen. Let staff send a reopened ticket straight back to the previous technician (Figure 9)."},
        {"step": "Resident follow-up by replying to the ticket email", "rating": "Missing", "who": "S1",
         "observation": "Replies to the ticket email are not linked to the ticket, and staff are not told unless they have the ticket open. The page refreshes every few minutes.",
         "implication": "Keep follow-ups inside the ticket and make them visible: unread marker and automatic refresh in the queue (Figure 6)."},
        {"step": "Show unit performance results", "rating": "Unnecessary", "who": "C1",
         "observation": "KPIs are reviewed each quarter, set by hand per contractor, and are not shown in the OFAM system. The system only records work orders and time taken.",
         "implication": "Keep 'Unit results' to jobs completed and average time. Do not build a KPI scoring module."},
        {"step": "Order spare parts and manage budget", "rating": "Out of scope", "who": "C1, T1",
         "observation": "Parts shortages and quarterly spending limits are real problems, but both said they sit outside the system.",
         "implication": "Do not model inventory or budget. Record only a hold reason."},
    ],
    "feedback": [
        {"code": "S1", "type": "Positive", "text": "The workflow in the diagram is clear and matches how the call center works."},
        {"code": "T1", "type": "Positive", "text": "The technician workflow is correct: the ticket comes from the call center, the job is done and closed in the system."},
        {"code": "C1", "type": "Positive", "text": "Limiting the system to work orders and time taken matches what OFAM records today."},
        {"code": "S1", "type": "Negative", "text": "Replies and follow-ups are hard to track. Staff only notice a reply if the ticket is open."},
        {"code": "S1", "type": "Negative", "text": "Without a ticket number, finding the ticket takes extra steps."},
        {"code": "T1", "type": "Negative", "text": "Parts are often not in stock, so jobs wait. The workflow has no clear place to show this."},
        {"code": "C1", "type": "Negative", "text": "Budget limits and manual KPIs sit outside the system, so the tool cannot fix them."},
    ],
    "suggestions": [
        {"code": "S1", "suggestion": "Make follow-ups visible to staff without opening each ticket.",
         "implication": "Add an unread marker and automatic refresh to the officer queue. Link replies to the ticket."},
        {"code": "S1", "suggestion": "Let staff find a ticket by room, student ID or ticket number.",
         "implication": "Add a search box to the officer queue (Figure 6)."},
        {"code": "S1, T1", "suggestion": "Show the resident when work is waiting for parts.",
         "implication": "Add a hold action with reason and expected date to the technician screen (Figure 7) and show it on the resident's progress line."},
        {"code": "C1", "suggestion": "Keep contractor performance simple.",
         "implication": "Keep the unit results table to jobs completed and average time."},
    ],
    "limitations": (
        "This evidence comes from the 11 November workflow review, where participants reacted to the process diagrams. "
        "Participants did not use the screens in Figures 4 to 9 themselves. A hands-on walkthrough of those screens "
        "with the same participants is still to be done. Participant codes are assigned by role. "
        "Findings are paraphrased, not quoted."
    ),
}
