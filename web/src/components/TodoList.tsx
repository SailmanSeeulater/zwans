import type { Todo } from "@/lib/todos";

const MARKS: Record<Todo["status"], string> = { completed: "✓", in_progress: "▸", pending: "○" };

/** The model's to-do list as a checklist. */
export function TodoList({ todos, title }: { todos: Todo[]; title?: string }) {
  const done = todos.filter((t) => t.status === "completed").length;
  return (
    <div className="todos">
      <div className="label">
        {title ?? "To-do"} · {done} of {todos.length} done
      </div>
      <ul>
        {todos.map((todo, i) => (
          <li key={i} className={`todo todo-${todo.status}`}>
            <span className="todo-mark" aria-hidden="true">
              {MARKS[todo.status]}
            </span>
            <span>{todo.content}</span>
            {todo.status === "in_progress" && <span className="sr-only"> (in progress)</span>}
            {todo.status === "completed" && <span className="sr-only"> (done)</span>}
          </li>
        ))}
      </ul>
    </div>
  );
}
