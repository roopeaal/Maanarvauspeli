CREATE TABLE IF NOT EXISTS game (
    id INT AUTO_INCREMENT PRIMARY KEY,
    username VARCHAR(50) NOT NULL UNIQUE,
    password VARCHAR(255) NOT NULL,
    points INT NOT NULL DEFAULT 1000,
    hiscore INT DEFAULT 0,
    kierroksen_Maa VARCHAR(100) DEFAULT NULL,
    arvottu_latitude DECIMAL(10, 6) DEFAULT NULL,
    arvottu_longitude DECIMAL(10, 6) DEFAULT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS country (
    iso_country CHAR(2) PRIMARY KEY,
    name VARCHAR(100) NOT NULL UNIQUE,
    latitude DECIMAL(10, 6) NOT NULL,
    longitude DECIMAL(10, 6) NOT NULL
);

CREATE TABLE IF NOT EXISTS airport (
    id INT AUTO_INCREMENT PRIMARY KEY,
    iso_country CHAR(2) NOT NULL,
    name VARCHAR(200) NOT NULL,
    type VARCHAR(50) NOT NULL,
    CONSTRAINT fk_airport_country
        FOREIGN KEY (iso_country) REFERENCES country(iso_country)
        ON DELETE CASCADE
        ON UPDATE CASCADE,
    INDEX idx_airport_country_type (iso_country, type),
    UNIQUE KEY uq_airport_country_name (iso_country, name)
);

INSERT INTO country (iso_country, name, latitude, longitude)
VALUES
    ('FI', 'Finland', 64.000000, 26.000000),
    ('SE', 'Sweden', 60.128161, 18.643501),
    ('NO', 'Norway', 60.472024, 8.468946),
    ('DE', 'Germany', 51.165691, 10.451526),
    ('FR', 'France', 46.227638, 2.213749),
    ('ES', 'Spain', 40.463667, -3.749220),
    ('IT', 'Italy', 41.871940, 12.567380),
    ('US', 'United States', 37.090240, -95.712891)
ON DUPLICATE KEY UPDATE
    name = VALUES(name),
    latitude = VALUES(latitude),
    longitude = VALUES(longitude);

INSERT INTO airport (iso_country, name, type)
VALUES
    ('FI', 'Helsinki Vantaa Airport', 'large_airport'),
    ('SE', 'Stockholm Arlanda Airport', 'large_airport'),
    ('NO', 'Oslo Gardermoen Airport', 'large_airport'),
    ('DE', 'Frankfurt Airport', 'large_airport'),
    ('FR', 'Charles de Gaulle International Airport', 'large_airport'),
    ('ES', 'Adolfo Suarez Madrid Barajas Airport', 'large_airport'),
    ('IT', 'Leonardo da Vinci Fiumicino Airport', 'large_airport'),
    ('US', 'Hartsfield Jackson Atlanta International Airport', 'large_airport')
ON DUPLICATE KEY UPDATE
    type = VALUES(type);
