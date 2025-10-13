"""
Test script to demonstrate both code_parser.py and git_processor.py working together.
"""

import os
import sys
from processors.code_parser import parse_repository_from_url
from processors.git_processor import GitProcessor
from dotenv import load_dotenv

load_dotenv()
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")

def test_repository_processing(repo_url, github_token=GITHUB_TOKEN):
    """Test processing a repository with both code parsing and metadata fetching."""
    print(f"🚀 Testing repository processing for: {repo_url}")
    print("=" * 60)

    # Test 1: code parsing
    print("\n Step 1: Parsing codebase...")
    try:
        functions_data = parse_repository_from_url(repo_url, "data/functions_test.json")
        print(f"✅ Code parsing completed: {len(functions_data)} entities found")

        type_counts = {}
        for item in functions_data:
            type_counts[item['type']] = type_counts.get(item['type'], 0) + 1

        print(" Code entities summary:")
        for entity_type, count in sorted(type_counts.items()):
            print(f"  {entity_type}: {count}")

    except Exception as e:
        print(f"❌ Code parsing failed: {e}")
        return False

    # Test 2: metadata fetching (commits and PRs)
    print("\n Step 2: Fetching repository metadata...")
    try:
        processor = GitProcessor(github_token=github_token)
        result = processor.process_repository(repo_url, "data")

        print(f"✅ Metadata fetching completed:")
        print(f"  Commits: {result['commits_count']}")
        print(f"  Pull Requests: {result['prs_count']}")

    except Exception as e:
        print(f"❌ Metadata fetching failed: {e}")
        return False

    print("\n🎉 All tests passed! Both components are working correctly.")
    return True

def main():
    """Main test function."""
    if len(sys.argv) < 2:
        print("Usage: python test_components.py <repo_url>")
        print("Example: python test_components.py https://github.com/microsoft/vscode")
        sys.exit(1)

    repo_url = sys.argv[1]

    os.makedirs("data", exist_ok=True)

    success = test_repository_processing(repo_url, github_token=GITHUB_TOKEN)

    if success:
        print("\n✅ Repository processing test completed successfully!")
        print("📁 Check the 'data' directory for output files:")
        print("  - functions_test.json (parsed code entities)")
        print("  - commits.json (commit history)")
        print("  - prs.json (pull request history)")
    else:
        print("\n❌ Repository processing test failed!")
        sys.exit(1)

if __name__ == "__main__":
    main()
