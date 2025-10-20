# git-lineage

## Description
This is a chatbot that leverages knowledge about a repository's commit history to better answer user queries.

## Project Link
https://zkhan04.github.io/git-lineage/

## Architecture
SQL Database: stores information about the codebase, including commits, files, and parsed symbols.

AWS Lambda serves as the core logic layer:
* Handles webhook or batch events from the code repository to ingest new data into the SQL database.
* Responds to user or application queries by combining database context with LLM output.
* Performs queries on the database to enhance LLM context.
  
AWS Bedrock: provides language model inference, and is called by the Lambda function when generating answers or performing semantic analysis.

Lambda ↔ Database interaction supports both data ingestion and contextual retrieval for user queries.

<img width="1238" height="856" alt="image" src="https://github.com/user-attachments/assets/383c6425-1025-4aed-b04a-c69a0eb5b44d" />
