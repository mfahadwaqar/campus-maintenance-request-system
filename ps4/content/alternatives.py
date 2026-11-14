ALTERNATIVES = {
    "offline": {
        "approach": "Service window, telephone, email, and walk-in requests, with paper completion forms.",
        "description": "Residents report faults at the service window, by telephone, by email, or in person. Call-center staff record each request by hand in FIMS. When work is finished in the field, the technician may collect the resident's signature on a paper completion form (OFAM-1, OFAM-2, T1).",
        "strengths": [
            {
                "title": "Needs no account.",
                "text": "Residents have no FIMS account, and an in-person or phone request requires nothing beyond their identity (OFAM-1, OFAM-2).",
            },
            {
                "title": "Fast for serious cases.",
                "text": "A resident who visited the office in person for a serious gas-pipe fault had a technician sent the next morning, and the ticket was created and assigned at the same time (R2, OFAM-3).",
            },
            {
                "title": "Works in the field.",
                "text": "A paper form records the resident's signature without a network connection (T1).",
            },
            {
                "title": "Personal contact.",
                "text": "Staff can call back for missing details before a ticket is issued (S1).",
            },
        ],
        "limitations": [
            "Replies and follow-ups are not linked to the ticket. Staff must re-enter them, or open a new ticket (S1).",
            "Residents often do not have the ticket number, so staff must search by room (S1).",
            "Quarterly reviews of contractor performance are compiled by hand, outside the system (C1).",
        ],
    },
    "comparators": [
        {
            "name": "Jira Service Management",
            "features": "As described in the proposal: service portal, email intake, configurable request types and workflows, queues, assignment, automation, reporting, and customer feedback (Atlassian, 2026).",
            "registration": "[Team to test: whether a requester must create an account to submit and track a request]",
            "usability": "[Team to test: time to submit and track a request in a trial account]",
            "limitations": "As described in the proposal: a broad enterprise platform, with configuration overhead for a single campus workflow.",
        },
        {
            "name": "MaintainX",
            "features": "As described in the proposal: maintenance requests, administrator approval or rejection, conversion to work orders, assignment to teams or individuals, status tracking, comments, notifications, locations, and photographs (MaintainX, 2026).",
            "registration": "[Team to test: whether the requester role needs an account]",
            "usability": "[Team to test: the requester's path from submission to status]",
            "limitations": "As described in the proposal: its broader industrial scope includes assets, recurring maintenance, and inventory.",
        },
        {
            "name": "FixMyStreet",
            "features": "As described in the proposal: public reporting of local problems, location and category routing, progress updates, and a later questionnaire (mySociety, n.d.).",
            "registration": "[Team to test: whether submission requires registration]",
            "usability": "[Team to test: the path from report to progress view]",
            "limitations": "As described in the proposal: a public reporting model with no internal roles, which does not suit private room details.",
        },
    ],
    "access_dates": "[Team to record the date and time each system was accessed, once tested.]",
    "local_comparator": "The current system is covered by a documentation request to OFAM. Interview findings describe its behaviour: it records call-center requests and work orders, contractors use it on the web and by phone, residents have no accounts, replies are not captured against the ticket, it refreshes at a set interval, and contractor performance is kept outside it (OFAM-1, OFAM-2, S1, T1, C1).",
    "fims_documentation": "[Title and date of the FIMS user guide, from OFAM.]",
    "team_statement": [
        "The comparators are general-purpose service or public reporting platforms. Each has useful features, such as queues, status tracking, and location-based routing. None was designed for a residence repair service that routes work to contractors, verifies a room before issue, and lets residents follow up without a shared account. FIMS is the closest comparator, and it is the system the residence service already uses, so it is the reference for what this project must add or keep.",
        "The comparison supports building a residence-specific application only if the gaps found in interviews are real and the application closes them. The gaps are: real-time updates to staff when a reply arrives, search by room and student ID, resident follow-up linked to the ticket, and recording the room check before a ticket is issued. If the trial tests show that a comparator already covers these, the team will reconsider the case for building the application.",
    ],
    "before_submission": "Complete the bracketed trial results and access dates for each comparator, and insert the FIMS documentation title and date. Remove any bracketed text that remains.",
}
