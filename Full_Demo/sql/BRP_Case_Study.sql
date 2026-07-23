######################### Creating the database and using it #########################
create database BRP_Case_Study
use BRP_Case_Study

######################### Creating the Schema as Per Submission.csv #########################

CREATE TABLE `submission` (
    `SubmissionID` BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY,
    `CustomerID` BIGINT NOT NULL,
    `ProductCode` VARCHAR(50) NOT NULL,
    `SubmissionType` VARCHAR(50),
    `PolicyType` VARCHAR(50),
    `Coverage` VARCHAR(255),
    `AgentID` BIGINT,
    `UnderwriterID` BIGINT,
    `Status` VARCHAR(50),
    `PriorStatus` VARCHAR(50),
    `ReasonforClosing` VARCHAR(255),
    `ApplicationDate` DATE,
    `SubmissionReceivedDate` DATE,
    `NeededByDate` DATE,
    `QuoteDate` DATE,
    `BindDate` DATE,
    `CloseDate` DATE,
    `SubmissionSource` VARCHAR(100),
    `ContactName` VARCHAR(100),
    `OperatingState` VARCHAR(50),
    `Industry` VARCHAR(100),
    `MainBusiness` VARCHAR(255),
    `AnnualRevenue` DECIMAL(15, 2),
    `PriorYearRevenue` DECIMAL(15, 2),
    `ProjectedRevenue` DECIMAL(15, 2),
    `YearsInBusiness` INT,
    `EmployeeCount` INT,
    `PriorClaimsCount` INT,
    `CurrentCarrier` VARCHAR(100),
    `CurrentLimit` DECIMAL(15, 2),
    `CurrentRetention` DECIMAL(15, 2),
    `CurrentPremium` DECIMAL(15, 2),
    `Bound` BOOLEAN,
    `CommissionRate` DECIMAL(5, 2),
    `NAICSCode` VARCHAR(10),
    `LastUpdatedDate` DATETIME
);