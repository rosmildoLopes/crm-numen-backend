
CREATE TABLE ai_usage (
	"key" VARCHAR(80) NOT NULL, 
	calls INTEGER NOT NULL, 
	PRIMARY KEY ("key")
)

;

CREATE TABLE automation_events (
	"key" VARCHAR(120) NOT NULL, 
	created_at DATETIME NOT NULL, 
	PRIMARY KEY ("key")
)

;

CREATE TABLE commercial_rules (
	id INTEGER NOT NULL, 
	followup_hours INTEGER NOT NULL, 
	auto_assign BOOLEAN NOT NULL, 
	followup_email BOOLEAN NOT NULL, 
	PRIMARY KEY (id)
)

;

CREATE TABLE courses (
	id INTEGER NOT NULL, 
	name VARCHAR(255) NOT NULL, 
	description TEXT NOT NULL, 
	price NUMERIC(12, 2) NOT NULL, 
	currency VARCHAR(3) NOT NULL, 
	active BOOLEAN NOT NULL, 
	campus_course_id VARCHAR(100), 
	PRIMARY KEY (id), 
	UNIQUE (name)
)

;

CREATE TABLE email_templates (
	"key" VARCHAR(60) NOT NULL, 
	subject VARCHAR(255) NOT NULL, 
	body TEXT NOT NULL, 
	PRIMARY KEY ("key")
)

;

CREATE TABLE users (
	id INTEGER NOT NULL, 
	email VARCHAR(255) NOT NULL, 
	full_name VARCHAR(255) NOT NULL, 
	password_hash VARCHAR(255) NOT NULL, 
	role VARCHAR(40) NOT NULL, 
	active BOOLEAN NOT NULL, 
	created_at DATETIME NOT NULL, 
	PRIMARY KEY (id)
)

;

CREATE TABLE worker_locks (
	"key" VARCHAR(60) NOT NULL, 
	expires_at DATETIME NOT NULL, 
	PRIMARY KEY ("key")
)

;

CREATE TABLE leads (
	id INTEGER NOT NULL, 
	first_name VARCHAR(120) NOT NULL, 
	last_name VARCHAR(120) NOT NULL, 
	email VARCHAR(255) NOT NULL, 
	phone VARCHAR(50) NOT NULL, 
	source VARCHAR(80) NOT NULL, 
	status VARCHAR(50) NOT NULL, 
	course_id INTEGER, 
	assigned_to_id INTEGER, 
	created_at DATETIME NOT NULL, 
	updated_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(course_id) REFERENCES courses (id), 
	FOREIGN KEY(assigned_to_id) REFERENCES users (id)
)

;

CREATE TABLE activities (
	id INTEGER NOT NULL, 
	lead_id INTEGER NOT NULL, 
	actor_id INTEGER, 
	action VARCHAR(60) NOT NULL, 
	detail TEXT NOT NULL, 
	created_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(lead_id) REFERENCES leads (id), 
	FOREIGN KEY(actor_id) REFERENCES users (id)
)

;

CREATE TABLE ai_drafts (
	id INTEGER NOT NULL, 
	lead_id INTEGER NOT NULL, 
	user_id INTEGER NOT NULL, 
	result TEXT NOT NULL, 
	model VARCHAR(100) NOT NULL, 
	created_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(lead_id) REFERENCES leads (id), 
	FOREIGN KEY(user_id) REFERENCES users (id)
)

;

CREATE TABLE commercial_tasks (
	id INTEGER NOT NULL, 
	lead_id INTEGER NOT NULL, 
	owner_id INTEGER NOT NULL, 
	title VARCHAR(255) NOT NULL, 
	detail TEXT NOT NULL, 
	due_at DATETIME NOT NULL, 
	status VARCHAR(20) NOT NULL, 
	created_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(lead_id) REFERENCES leads (id), 
	FOREIGN KEY(owner_id) REFERENCES users (id)
)

;

CREATE TABLE contact_logs (
	id INTEGER NOT NULL, 
	lead_id INTEGER NOT NULL, 
	actor_id INTEGER NOT NULL, 
	channel VARCHAR(30) NOT NULL, 
	outcome VARCHAR(40) NOT NULL, 
	detail TEXT NOT NULL, 
	created_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(lead_id) REFERENCES leads (id), 
	FOREIGN KEY(actor_id) REFERENCES users (id)
)

;

CREATE TABLE lead_notes (
	id INTEGER NOT NULL, 
	lead_id INTEGER NOT NULL, 
	author_id INTEGER NOT NULL, 
	text TEXT NOT NULL, 
	created_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(lead_id) REFERENCES leads (id) ON DELETE CASCADE, 
	FOREIGN KEY(author_id) REFERENCES users (id)
)

;

CREATE TABLE notifications (
	id INTEGER NOT NULL, 
	user_id INTEGER NOT NULL, 
	lead_id INTEGER, 
	event_key VARCHAR(120) NOT NULL, 
	title VARCHAR(255) NOT NULL, 
	message TEXT NOT NULL, 
	read BOOLEAN NOT NULL, 
	created_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (user_id, event_key), 
	FOREIGN KEY(user_id) REFERENCES users (id), 
	FOREIGN KEY(lead_id) REFERENCES leads (id)
)

;

CREATE TABLE outbox (
	id INTEGER NOT NULL, 
	lead_id INTEGER, 
	kind VARCHAR(60) NOT NULL, 
	recipient VARCHAR(255) NOT NULL, 
	subject VARCHAR(255) NOT NULL, 
	body TEXT NOT NULL, 
	status VARCHAR(30) NOT NULL, 
	created_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(lead_id) REFERENCES leads (id)
)

;

CREATE TABLE sales (
	id INTEGER NOT NULL, 
	lead_id INTEGER NOT NULL, 
	course_id INTEGER NOT NULL, 
	amount NUMERIC(12, 2) NOT NULL, 
	payment_reference VARCHAR(255) NOT NULL, 
	status VARCHAR(30) NOT NULL, 
	created_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(lead_id) REFERENCES leads (id), 
	FOREIGN KEY(course_id) REFERENCES courses (id), 
	UNIQUE (payment_reference)
)

;

CREATE TABLE email_deliveries (
	outbox_id INTEGER NOT NULL, 
	attempts INTEGER NOT NULL, 
	error TEXT NOT NULL, 
	updated_at DATETIME NOT NULL, 
	PRIMARY KEY (outbox_id), 
	FOREIGN KEY(outbox_id) REFERENCES outbox (id)
)

;
