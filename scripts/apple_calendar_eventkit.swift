import EventKit
import Foundation

private struct CalendarRow: Encodable {
    let title: String
    let start: String
    let end: String
    let allDay: Bool

    enum CodingKeys: String, CodingKey {
        case title
        case start
        case end
        case allDay = "all_day"
    }
}

private func fail(_ reason: String) -> Never {
    FileHandle.standardError.write(Data("calendar helper failed: \(reason)\n".utf8))
    exit(1)
}

private func parseDate(_ value: String) -> Date? {
    let fractional = ISO8601DateFormatter()
    fractional.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
    if let parsed = fractional.date(from: value) {
        return parsed
    }
    let regular = ISO8601DateFormatter()
    regular.formatOptions = [.withInternetDateTime]
    return regular.date(from: value)
}

private func requestCalendarAccess(_ store: EKEventStore) -> Bool {
    let semaphore = DispatchSemaphore(value: 0)
    let lock = NSLock()
    var granted = false

    let completion: EKEventStoreRequestAccessCompletionHandler = { allowed, _ in
        lock.lock()
        granted = allowed
        lock.unlock()
        semaphore.signal()
    }

    if #available(macOS 14.0, *) {
        store.requestFullAccessToEvents(completion: completion)
    } else {
        store.requestAccess(to: .event, completion: completion)
    }

    // The first permission decision is made by the user, so allow enough time
    // for the system prompt without making ordinary background queries slower.
    guard semaphore.wait(timeout: .now() + 90) == .success else {
        return false
    }
    lock.lock()
    defer { lock.unlock() }
    return granted
}

@main
private struct AppleCalendarAgendaReader {
    static func main() {
        let environment = ProcessInfo.processInfo.environment
        guard
            let startValue = environment["BJTU_CALENDAR_START"],
            let endValue = environment["BJTU_CALENDAR_END"],
            let outputValue = environment["BJTU_CALENDAR_OUTPUT"],
            let start = parseDate(startValue),
            let end = parseDate(endValue),
            end > start
        else {
            fail("invalid bounded request")
        }

        let store = EKEventStore()
        guard requestCalendarAccess(store) else {
            fail("calendar access denied or timed out")
        }

        let formatter = ISO8601DateFormatter()
        formatter.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        let predicate = store.predicateForEvents(
            withStart: start,
            end: end,
            calendars: nil
        )
        let rows = store.events(matching: predicate)
            .sorted {
                if $0.startDate == $1.startDate {
                    return ($0.title ?? "") < ($1.title ?? "")
                }
                return $0.startDate < $1.startDate
            }
            .map {
                CalendarRow(
                    title: $0.title ?? "",
                    start: formatter.string(from: $0.startDate),
                    end: formatter.string(from: $0.endDate),
                    allDay: $0.isAllDay
                )
            }

        let data: Data
        do {
            data = try JSONEncoder().encode(rows)
        } catch {
            fail("could not encode response")
        }

        guard let handle = FileHandle(forWritingAtPath: outputValue) else {
            fail("private response file unavailable")
        }
        do {
            try handle.truncate(atOffset: 0)
            try handle.write(contentsOf: data)
            try handle.synchronize()
            try handle.close()
        } catch {
            fail("could not write private response")
        }
    }
}
