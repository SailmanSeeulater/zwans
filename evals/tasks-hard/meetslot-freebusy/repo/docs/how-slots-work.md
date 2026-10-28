# How meetslot finds a slot

1. For each person, take the shifts that can touch the search window
   (`Person.working_time`). Working hours are local; meetslot converts them to UTC with
   the person's fixed `utc_offset`. Night shifts (end not after start) end the next day.
2. Take out each busy interval, widened by the buffer on both sides (`free_time`).
3. Intersect everyone's free time.
4. Walk each free interval and list every start on the step grid (counted from 00:00 UTC)
   where the whole meeting fits.

Everything in the library is UTC; only the CLI shows local times. `IntervalSet` is the
workhorse: it keeps its intervals normalised (sorted, merged when they overlap or touch).
