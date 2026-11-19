VALID_DECISIONS = {"add", "change", "keep", "defer", "remove"}

MVP_DECISIONS = [
    {"feature":"Resident web submission","decision":"add","reason":"Direct submission is a core replacement for counter, phone, and repeated email contact.","scope":"resident ticket creation"},
    {"feature":"Ticket number status lookup","decision":"add","reason":"Students struggle to quote numbers and see replies.","scope":"resident-facing status"},
    {"feature":"Call Center Staff intake for phone, email, and walk-in","decision":"add","reason":"Call Center Staff enter requests received by phone or in person.","scope":"staff intake"},
    {"feature":"Category-based unit dispatch","decision":"keep","reason":"Work is already dispatched to units by category; automatic routing remains unconfirmed.","scope":"assignment"},
    {"feature":"Resident and staff comments with follow-up flag","decision":"add","reason":"The resident follow-up problem and staff follow-up queue require linked discussion.","scope":"comments"},
    {"feature":"Technician/Contractor completion and signature flag","decision":"add","reason":"Completion records whether the resident signed on site and may include a completion photo.","scope":"completion"},
    {"feature":"Resident verification window","decision":"keep","reason":"Residents may verify or reopen completed work after system closure.","scope":"verification"},
    {"feature":"Status guard on direct database updates","decision":"add","reason":"Allowed transitions should be enforced by the application and database.","scope":"workflow integrity"},
    {"feature":"Unit results without scores","decision":"add","reason":"Units can view completed-job counts and average completion time without targets or rankings.","scope":"reporting"},
    {"feature":"Guest access code","decision":"remove","reason":"Not part of the approved MVP.","scope":"access"},
    {"feature":"Technician/Contractor specialization","decision":"remove","reason":"Not part of the approved MVP.","scope":"assignment"},
    {"feature":"Service targets","decision":"defer","reason":"ServiceTarget is intentionally not implemented.","scope":"reporting"},
    {"feature":"Internal comments","decision":"defer","reason":"Internal comment behavior is not yet approved.","scope":"comments"},
    {"feature":"HTTP 409 optimistic concurrency","decision":"defer","reason":"Version checking is planned for a later stage.","scope":"workflow integrity"},
]
