CREATE TABLE users (
	id INTEGER NOT NULL, 
	email VARCHAR(255) NOT NULL, 
	full_name VARCHAR(255) NOT NULL, 
	password_hash VARCHAR(255) NOT NULL, 
	role VARCHAR(40) NOT NULL, 
	active BOOLEAN NOT NULL, 
	created_at DATETIME NOT NULL, 
	PRIMARY KEY (id)
);
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
);
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
);
CREATE TABLE lead_notes (
	id INTEGER NOT NULL, 
	lead_id INTEGER NOT NULL, 
	author_id INTEGER NOT NULL, 
	text TEXT NOT NULL, 
	created_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(lead_id) REFERENCES leads (id) ON DELETE CASCADE, 
	FOREIGN KEY(author_id) REFERENCES users (id)
);
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
);
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
);
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
);
