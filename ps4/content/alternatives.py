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
    "review_summary": "For: project partner. Task: visit the commercial and public comparators, record access times, take screenshots, and compare pros and cons with our system. Checked on 14 November 2026, between about 19:19 and 19:21 local time, in Chrome, without signing in.",
    "what_was_done": [
        "FixMyStreet: opened the site, searched a location, reached the report form, and picked a category. No report was submitted because reports go to a real council. The form returned 'Bad recaptcha' at the next step, so the walkthrough stops there. The check was not bypassed.",
        "Jira Service Management and MaintainX: only the public home pages were opened. Both ask users to sign up before using the product. No accounts were created, so the requester path, registration answer, and time-to-submit were not tested for these two.",
        "FIMS: nothing to test. Its row depends on the user guide requested from OFAM.",
        "Do not present Jira Service Management or MaintainX as used. Say 'home page reviewed' unless the team completes a trial.",
    ],
    "access_records": [
        {
            "system": "FixMyStreet",
            "address": "fixmystreet.com",
            "accessed": "14 November 2026, about 19:19",
            "reached": "Home page, location search, and category form. Blocked by reCAPTCHA at the next step.",
        },
        {
            "system": "Jira Service Management",
            "address": "atlassian.com/software/jira/service-management",
            "accessed": "14 November 2026, about 19:20",
            "reached": "Public product page with a sign-up form.",
        },
        {
            "system": "MaintainX",
            "address": "getmaintainx.com",
            "accessed": "14 November 2026, about 19:21",
            "reached": "Public home page with Sign Up for Free and Schedule Demo.",
        },
        {
            "system": "FIMS (local)",
            "address": "Not public",
            "accessed": "Not accessed",
            "reached": "The OFAM user guide was not available for review.",
        },
    ],
    "screenshots": [
        {
            "figure": "Figure A1",
            "image": "ps4/alternatives_images/figure-a1.jpg",
            "caption": "FixMyStreet home page, 14 November 2026, about 19:19. Postcode or street search, 'Use my current location', or start with a photo.",
        },
        {
            "figure": "Figure A2",
            "image": "ps4/alternatives_images/figure-a2.jpg",
            "caption": "FixMyStreet location search for 'Tib St, Manchester'. It lists four matching streets. No sign-in asked.",
        },
        {
            "figure": "Figure A3",
            "image": "ps4/alternatives_images/figure-a3.jpg",
            "caption": "FixMyStreet report form. The category list is set by the local council. Map tiles did not draw in this session.",
        },
        {
            "figure": "Figure A4",
            "image": "ps4/alternatives_images/figure-a4.jpg",
            "caption": "FixMyStreet returned 'Bad recaptcha' at the next step. No report was sent.",
        },
        {
            "figure": "Figure A5",
            "image": "ps4/alternatives_images/figure-a5.jpg",
            "caption": "Jira Service Management product page with a work-email sign-up form (also Google, Microsoft, Apple, Slack).",
        },
        {
            "figure": "Figure A6",
            "image": "ps4/alternatives_images/figure-a6.jpg",
            "caption": "MaintainX home page with 'Sign Up for Free' and 'Schedule Demo'.",
        },
    ],
    "screenshots_note": "The screenshots are real captures, taken at reduced size. They show the pages as they were, not edited.",
    "comparators": [
        {
            "name": "Jira Service Management",
            "features": "As described in the proposal: service portal, email intake, configurable request types and workflows, queues, assignment, automation, reporting, and customer feedback (Atlassian, 2026).",
            "registration": "The public page asks for a work email, or Google, Microsoft, Apple or Slack sign-in, before use. Whether a requester needs an account was not tested.",
            "usability": "Not timed. The sign-up form is one field on the page. Not tested beyond that.",
            "limitations": "As described in the proposal: a broad enterprise platform, with configuration overhead for a single campus workflow.",
        },
        {
            "name": "MaintainX",
            "features": "As described in the proposal: maintenance requests, administrator approval or rejection, conversion to work orders, assignment to teams or individuals, status tracking, comments, notifications, locations, and photographs (MaintainX, 2026).",
            "registration": "The home page offers 'Sign Up for Free' and 'Schedule Demo'. Whether a requester needs an account was not tested.",
            "usability": "Not timed. Not tested beyond the home page.",
            "limitations": "As described in the proposal: its broader industrial scope includes assets, recurring maintenance, and inventory.",
        },
        {
            "name": "FixMyStreet",
            "features": "As described in the proposal: public reporting of local problems, location and category routing, progress updates, and a later questionnaire (mySociety, n.d.).",
            "registration": "No account needed. The site's FAQ says you can report without registering and confirm by an emailed link. Name and email are required, and reports are public.",
            "registration_follow_up": "",
            "usability": "Search, pick a location and category took under a minute in this session. A full report could not be completed or timed because reCAPTCHA stopped the attempt.",
            "usability_follow_up": "",
            "limitations": "As described in the proposal: a public reporting model with no internal roles, which does not suit private room details.",
        },
    ],
    "access_date_summary": "FixMyStreet, Jira Service Management and MaintainX home pages accessed on 14 November 2026 (about 19:19 to 19:21). Requester walkthroughs for Jira and MaintainX not completed.",
    "pros_cons": [
        {
            "system": "Jira Service Management",
            "pros": "Mature queues, assignment, automation, reporting and customer feedback (as described by the vendor). Handles email intake.",
            "cons": "Broad enterprise platform: setup and configuration for one campus workflow. Sign-up is aimed at teams. No room verification before a request is issued. Contractor result tracking would have to be configured.",
        },
        {
            "system": "MaintainX",
            "pros": "Work orders, assignment to teams or individuals, status tracking, comments, locations and photographs (vendor description). Closest match to our technician side.",
            "cons": "Industrial scope: assets, recurring maintenance, inventory. Our users do not need that. Paid product beyond the free tier. No resident verify-or-reopen step.",
        },
        {
            "system": "FixMyStreet",
            "pros": "Needs no account. Very short path: place, category, description. Public progress and updates. Reports routed to the right authority by location.",
            "cons": "Public by design, so it does not suit private room details. No internal roles: no staff queue, no technician work order, no contractor view. Residents cannot verify the repair against a room.",
        },
        {
            "system": "FIMS (current system)",
            "pros": "Already in use. Web and phone intake. Residents need no account.",
            "cons": "Replies not linked to the ticket, no ticket number for callers, contractor performance kept outside (OFAM-1, OFAM-2, S1, T1, C1).",
        },
    ],
    "system_adds": "Room verification before issue, separate resident, call-center and technician views, resident verify or reopen, status history, and follow-ups kept inside the ticket.",
    "local_comparator": "The current system is covered by a documentation request to OFAM. Interview findings describe its behaviour: it records call-center requests and work orders, contractors use it on the web and by phone, residents have no accounts, replies are not captured against the ticket, it refreshes at a set interval, and contractor performance is kept outside it (OFAM-1, OFAM-2, S1, T1, C1).",
    "team_statement": [
        "The comparators are general-purpose service or public reporting platforms. Each has useful features, such as queues, status tracking, and location-based routing. None was designed for a residence repair service that routes work to contractors, verifies a room before issue, and lets residents follow up without a shared account. FIMS is the closest comparator, and it is the system the residence service already uses, so it is the reference for what this project must add or keep.",
        "The comparison supports building a residence-specific application only if the gaps found in interviews are real and the application closes them. The gaps are: real-time updates to staff when a reply arrives, search by room and student ID, resident follow-up linked to the ticket, and recording the room check before a ticket is issued. If the trial tests show that a comparator already covers these, the team will reconsider the case for building the application.",
    ],
}
