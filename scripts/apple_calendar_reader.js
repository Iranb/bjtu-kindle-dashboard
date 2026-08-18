function run() {
  ObjC.import("Foundation");
  const calendar = Application("Calendar");
  const environment = $.NSProcessInfo.processInfo.environment;
  const start = new Date(ObjC.unwrap(environment.objectForKey("BJTU_CALENDAR_START")));
  const end = new Date(ObjC.unwrap(environment.objectForKey("BJTU_CALENDAR_END")));
  const rows = [];
  for (const source of calendar.calendars()) {
    let events = [];
    try {
      events = source.events.whose({_and: [
        {startDate: {_lessThan: end}},
        {endDate: {_greaterThan: start}}
      ]})();
    } catch (error) {
      continue;
    }
    for (const event of events) {
      try {
        rows.push({
          title: String(event.summary() || ""),
          start: event.startDate().toISOString(),
          end: event.endDate().toISOString(),
          all_day: Boolean(event.alldayEvent())
        });
      } catch (error) {}
    }
  }
  const result = $(JSON.stringify(rows));
  const outputPath = environment.objectForKey("BJTU_CALENDAR_OUTPUT");
  const ok = result.writeToFileAtomicallyEncodingError(
    outputPath,
    true,
    $.NSUTF8StringEncoding,
    null
  );
  if (!ok) {
    throw new Error("cannot write calendar response");
  }
  return "ok";
}
